"""Bounded local-header and CRC checks; no filesystem extraction."""
import struct
import threading
import time
import zlib

from core.zip_rules import ArchiveRejected

MAX_COMPRESSED = 128 * 1024 ** 2
MAX_UNCOMPRESSED = 256 * 1024 ** 2
MAX_LOCAL_EXTRA = 4096
MAX_LOCAL_METADATA = 4 * 1024 ** 2
MAX_SECONDS = 30
CHUNK = 64 * 1024
_LOCAL = struct.Struct('<4s5H3I2H')
_LIMIT = threading.BoundedSemaphore(1)


class VerificationBusy(ValueError):
    """Only one resource-intensive verification can run at a time."""


def _read_exact(source, length, deadline):
    if time.monotonic() > deadline:
        raise ArchiveRejected('Превышено время проверки ZIP')
    data = source.read(length)
    if len(data) != length:
        raise ArchiveRejected('Данные ZIP обрезаны')
    return data


def _extra(data):
    position = 0
    while position < len(data):
        if position + 4 > len(data):
            raise ArchiveRejected('Повреждено дополнительное поле локального заголовка')
        field, length = struct.unpack_from('<HH', data, position)
        position += 4 + length
        if position > len(data) or field == 1:
            raise ArchiveRejected('Повреждённое поле или ZIP64 не поддерживается')


def _header(source, info, boundary, deadline):
    source.seek(info.header_offset)
    data = _read_exact(source, _LOCAL.size, deadline)
    signature, version, flags, method, mod_time, mod_date, crc, compressed, size, name_len, extra_len = _LOCAL.unpack(data)
    year, month, day, _, _, _ = info.date_time
    expected_date = ((year - 1980) << 9) | (month << 5) | day
    raw_name = info.orig_filename.encode('utf-8' if info.flag_bits & 0x800 else 'cp437')
    if (signature != b'PK\x03\x04' or version != info.extract_version or flags != info.flag_bits or
            method != info.compress_type or mod_time != info._raw_time or mod_date != expected_date or
            name_len != len(raw_name) or extra_len > MAX_LOCAL_EXTRA):
        raise ArchiveRejected('Локальный заголовок ZIP не совпадает с центральным каталогом')
    if flags & ~(0x800 | 0x08 | 0x06) or (method == 0 and flags & 0x06):
        raise ArchiveRejected('Флаги ZIP для проверки данных не поддерживаются')
    if flags & 0x08:
        if crc not in (0, info.CRC) or compressed not in (0, info.compress_size) or size not in (0, info.file_size):
            raise ArchiveRejected('Размеры в локальном заголовке ZIP не совпадают')
    elif (crc, compressed, size) != (info.CRC, info.compress_size, info.file_size):
        raise ArchiveRejected('Размеры или CRC локального заголовка ZIP не совпадают')
    header_size = _LOCAL.size + name_len + extra_len
    descriptor_size = 12 if flags & 0x08 else 0
    if info.header_offset + header_size + info.compress_size + descriptor_size > boundary:
        raise ArchiveRejected('Записи ZIP пересекаются или выходят за каталог')
    if _read_exact(source, name_len, deadline) != raw_name:
        raise ArchiveRejected('Имя в локальном заголовке ZIP не совпадает')
    _extra(_read_exact(source, extra_len, deadline))
    return header_size


def _payload(source, info, deadline):
    crc, size, remaining = 0, 0, info.compress_size
    decoder = zlib.decompressobj(-15) if info.compress_type == 8 else None

    def add(data):
        nonlocal crc, size
        size += len(data)
        if size > info.file_size:
            raise ArchiveRejected('Фактический размер данных ZIP превышает заявленный')
        crc = zlib.crc32(data, crc)

    while remaining:
        chunk = _read_exact(source, min(CHUNK, remaining), deadline)
        remaining -= len(chunk)
        if decoder is None:
            add(chunk)
            continue
        try:
            while chunk:
                if time.monotonic() > deadline:
                    raise ArchiveRejected('Превышено время проверки ZIP')
                add(decoder.decompress(chunk, CHUNK))
                chunk = decoder.unconsumed_tail
                if decoder.unused_data or decoder.eof and (chunk or remaining):
                    raise ArchiveRejected('Лишние данные после потока сжатия ZIP')
        except zlib.error as exc:
            raise ArchiveRejected('Повреждён поток сжатия ZIP') from exc
    if decoder is not None and not decoder.eof:
        raise ArchiveRejected('Поток сжатия ZIP не завершён')
    if size != info.file_size or crc & 0xffffffff != info.CRC:
        raise ArchiveRejected('Размер или CRC данных ZIP не совпадают')


def _descriptor(source, info, boundary, deadline):
    if not info.flag_bits & 0x08:
        return
    first = _read_exact(source, 4, deadline)
    signed = first == b'PK\x07\x08'
    remaining = 12 if signed else 8
    if source.tell() + remaining > boundary:
        raise ArchiveRejected('Дескриптор ZIP пересекает другую запись')
    data = _read_exact(source, remaining, deadline)
    crc, compressed, size = struct.unpack('<III', data if signed else first + data)
    if (crc, compressed, size) != (info.CRC, info.compress_size, info.file_size):
        raise ArchiveRejected('Дескриптор данных ZIP не совпадает')


def verify_content(source, entries, directory_offset):
    if not _LIMIT.acquire(blocking=False):
        raise VerificationBusy('Другая проверка ZIP уже выполняется')
    try:
        if sum(e.compress_size for e in entries) > MAX_COMPRESSED or sum(e.file_size for e in entries) > MAX_UNCOMPRESSED:
            raise ArchiveRejected('ZIP превышает лимит проверки данных: 128 МиБ сжатых или 256 МиБ распакованных')
        ordered = sorted(entries, key=lambda e: e.header_offset)
        if ordered and ordered[0].header_offset != 0:
            raise ArchiveRejected('Самораспаковывающиеся и нестандартные ZIP не поддерживаются')
        if len({e.header_offset for e in ordered}) != len(ordered):
            raise ArchiveRejected('Локальные записи ZIP имеют одинаковые смещения')
        deadline, metadata = time.monotonic() + MAX_SECONDS, 0
        for index, info in enumerate(ordered):
            boundary = ordered[index + 1].header_offset if index + 1 < len(ordered) else directory_offset
            metadata += _header(source, info, boundary, deadline)
            if metadata > MAX_LOCAL_METADATA:
                raise ArchiveRejected('Слишком много локальных метаданных ZIP')
            _payload(source, info, deadline)
            _descriptor(source, info, boundary, deadline)
        return {'verified_files': sum(not e.is_dir() for e in entries),
                'verified_bytes': sum(e.file_size for e in entries)}
    finally:
        _LIMIT.release()
