"""Bounded ZIP central-directory inspection. No decompression or writes."""
import os
from pathlib import Path
import stat
import struct
import zipfile

from core.zip_rules import ArchiveRejected, MAX_ENTRIES, check_zip_entries
from storage.incoming_downloads import stat_identity
from storage.zip_content import verify_content

MAX_DIRECTORY_BYTES = 4 * 1024 * 1024
_EOCD = struct.Struct('<4s4H2IH')
_CENTRAL = struct.Struct('<4s6H3I5H2I')


class ArchiveChanged(ValueError):
    """The inspected path no longer identifies the file the user selected."""


def _regular(info):
    reparse = getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)
    return stat.S_ISREG(info.st_mode) and not (getattr(info, 'st_file_attributes', 0) & reparse)


def _read_directory(source, size):
    tail_size = min(size, 65535 + _EOCD.size)
    source.seek(size - tail_size)
    tail = source.read(tail_size)
    if len(tail) != tail_size:
        raise ArchiveRejected('ZIP был изменён или обрезан')
    pos = tail.rfind(b'PK\x05\x06')
    if pos < 0 or pos + _EOCD.size > len(tail):
        raise ArchiveRejected('Не найден конец центрального каталога ZIP')
    signature, disk, cd_disk, disk_entries, count, length, offset, comment = _EOCD.unpack_from(tail, pos)
    end_position = size - tail_size + pos
    if pos + _EOCD.size + comment != len(tail):
        raise ArchiveRejected('Некорректный конец ZIP или комментарий')
    if disk or cd_disk or disk_entries != count:
        raise ArchiveRejected('Многотомные ZIP не поддерживаются')
    if count == 0xffff or length == 0xffffffff or offset == 0xffffffff:
        raise ArchiveRejected('ZIP64 пока не поддерживается')
    if not count or count > MAX_ENTRIES or length > MAX_DIRECTORY_BYTES:
        raise ArchiveRejected('Пустой ZIP или превышен предел размера каталога ZIP')
    if offset + length != end_position:
        raise ArchiveRejected('Необычная структура ZIP или самораспаковывающийся архив')
    source.seek(offset)
    data = source.read(length)
    if len(data) != length:
        raise ArchiveRejected('Центральный каталог ZIP обрезан')
    return data, count, offset


def _entries(data, count, directory_offset):
    pos, entries = 0, []
    while pos < len(data):
        if len(entries) >= MAX_ENTRIES or pos + _CENTRAL.size > len(data):
            raise ArchiveRejected('Некорректное число элементов ZIP')
        fields = _CENTRAL.unpack_from(data, pos)
        signature, made, needed, flags, method, mod_time, mod_date, crc, compressed, uncompressed, name_len, extra_len, comment_len, disk, _, attrs, local_offset = fields
        if signature != b'PK\x01\x02' or disk or 0xffffffff in (compressed, uncompressed, local_offset):
            raise ArchiveRejected('Некорректная или неподдерживаемая запись ZIP')
        end = pos + _CENTRAL.size + name_len + extra_len + comment_len
        if end > len(data) or local_offset >= directory_offset:
            raise ArchiveRejected('Некорректные размеры или смещение записи ZIP')
        name_start = pos + _CENTRAL.size
        raw_name = data[name_start:name_start + name_len]
        extra = data[name_start + name_len:name_start + name_len + extra_len]
        cursor = 0
        while cursor < len(extra):
            if cursor + 4 > len(extra):
                raise ArchiveRejected('Повреждённое дополнительное поле ZIP')
            field, field_size = struct.unpack_from('<HH', extra, cursor)
            cursor += 4 + field_size
            if cursor > len(extra) or field == 1:
                raise ArchiveRejected('Повреждённое дополнительное поле или ZIP64 не поддерживается')
        try:
            name = raw_name.decode('utf-8' if flags & 0x800 else 'cp437')
            info = zipfile.ZipInfo(name)
        except (UnicodeError, ValueError, IndexError) as exc:
            raise ArchiveRejected('Некорректное имя внутри ZIP') from exc
        info.create_system = made >> 8
        info.flag_bits, info.compress_type, info.external_attr = flags, method, attrs
        info.compress_size, info.file_size = compressed, uncompressed
        info.CRC, info.header_offset, info.extract_version = crc, local_offset, needed
        info._raw_time = mod_time
        info.date_time = ((mod_date >> 9) + 1980, (mod_date >> 5) & 15, mod_date & 31,
                          mod_time >> 11, (mod_time >> 5) & 63, (mod_time & 31) * 2)
        entries.append(info)
        pos = end
    if len(entries) != count:
        raise ArchiveRejected('Число записей ZIP не совпадает с каталогом')
    return entries


def ensure_identity(path, expected_identity):
    try:
        info = Path(path).lstat()
    except FileNotFoundError as exc:
        raise ArchiveChanged('Архив был перемещён во время проверки') from exc
    if not _regular(info) or stat_identity(info) != expected_identity:
        raise ArchiveChanged('Архив изменился во время проверки')


def inspect_zip(path, expected_identity, verify_data=False, include_names=False):
    path = Path(path)
    try:
        before = path.lstat()
        if not _regular(before) or stat_identity(before) != expected_identity:
            raise ArchiveChanged('Архив изменился или стал ссылкой: обновите поиск')
        flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0)
        fd = os.open(path, flags)
    except FileNotFoundError as exc:
        raise ArchiveChanged('Архив больше недоступен: обновите поиск') from exc
    with os.fdopen(fd, 'rb') as source:
        opened = os.fstat(source.fileno())
        if not _regular(opened) or stat_identity(opened) != expected_identity:
            raise ArchiveChanged('Архив изменился: обновите поиск')
        data, count, offset = _read_directory(source, opened.st_size)
        entries = _entries(data, count, offset)
        result = check_zip_entries(entries)
        if verify_data:
            result.update(verify_content(source, entries, offset))
        if include_names:
            result['_entries'] = [{'path': entry.filename, 'kind': 'directory' if entry.is_dir() else 'file'}
                                  for entry in entries]
        try:
            after_path = path.lstat()
        except FileNotFoundError as exc:
            raise ArchiveChanged('Архив был перемещён во время проверки') from exc
        after_file = os.fstat(source.fileno())
        if not _regular(after_path) or any(stat_identity(info) != expected_identity for info in (after_file, after_path)):
            raise ArchiveChanged('Архив изменился во время проверки')
        return result
