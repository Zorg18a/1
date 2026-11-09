"""Conservative ZIP metadata checks; never interprets them as proof of safety."""
import stat
import unicodedata
import zipfile

MAX_ENTRIES = 5000
MAX_ENTRY_SIZE = 20 * 1024 ** 3
MAX_TOTAL_SIZE = 80 * 1024 ** 3
MAX_DEPTH = 64
MAX_PATH_UNITS = 240
MAX_RATIO = 1000
_RESERVED = {'CON', 'PRN', 'AUX', 'NUL', 'CONIN$', 'CONOUT$'} | {
    f'{prefix}{number}' for prefix in ('COM', 'LPT') for number in range(1, 10)
}


class ArchiveRejected(ValueError):
    """Archive metadata fails the deliberately conservative preliminary policy."""


def _components(info):
    name = info.orig_filename
    if name != info.filename or not name or name.startswith('/') or '\\' in name:
        raise ArchiveRejected('Недопустимый путь внутри ZIP')
    if any(ord(char) < 32 or ord(char) == 127 or char in '<>:"|?*' for char in name):
        raise ArchiveRejected('Недопустимые символы в пути ZIP')
    try:
        units = len(name.encode('utf-16-le')) // 2
    except UnicodeEncodeError as exc:
        raise ArchiveRejected('Некорректный Unicode в имени ZIP') from exc
    if units > MAX_PATH_UNITS:
        raise ArchiveRejected('Слишком длинный путь внутри ZIP')
    parts = name[:-1].split('/') if name.endswith('/') else name.split('/')
    if not parts or len(parts) > MAX_DEPTH:
        raise ArchiveRejected('Слишком большая вложенность ZIP')
    for part in parts:
        if part in ('', '.', '..') or part.endswith((' ', '.')):
            raise ArchiveRejected('Недопустимый компонент пути ZIP')
        stem = unicodedata.normalize('NFKC', part).split('.')[0].upper()
        if stem in _RESERVED:
            raise ArchiveRejected('Зарезервированное имя Windows в ZIP')
    return parts


def check_zip_entries(entries):
    if len(entries) > MAX_ENTRIES:
        raise ArchiveRejected('Слишком много элементов ZIP')
    total, files, explicit, spellings, types = 0, 0, set(), {}, {}
    for info in entries:
        parts = _components(info)
        if info.flag_bits & (1 | 0x40):
            raise ArchiveRejected('Зашифрованные ZIP не поддерживаются')
        if info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
            raise ArchiveRejected('Метод сжатия ZIP не поддерживается')
        mode = (info.external_attr >> 16) if info.create_system == 3 else 0
        kind = stat.S_IFMT(mode)
        if kind not in (0, stat.S_IFREG, stat.S_IFDIR):
            raise ArchiveRejected('Ссылки и специальные файлы ZIP не поддерживаются')
        is_dir = info.is_dir()
        if (kind == stat.S_IFDIR and not is_dir) or (kind == stat.S_IFREG and is_dir):
            raise ArchiveRejected('Тип элемента ZIP не совпадает с именем')
        if info.file_size > MAX_ENTRY_SIZE:
            raise ArchiveRejected('Слишком большой файл внутри ZIP')
        if info.file_size and (not info.compress_size or
                info.file_size > 10 * 1024 ** 2 and info.file_size > info.compress_size * MAX_RATIO):
            raise ArchiveRejected('Подозрительно высокая степень сжатия ZIP')
        if is_dir and info.file_size:
            raise ArchiveRejected('Каталог ZIP содержит данные')
        total += info.file_size
        if total > MAX_TOTAL_SIZE:
            raise ArchiveRejected('Слишком большой суммарный размер ZIP')
        files += not is_dir
        for i in range(1, len(parts) + 1):
            original = '/'.join(parts[:i])
            canonical = unicodedata.normalize('NFC', original).casefold()
            desired = 'dir' if i < len(parts) or is_dir else 'file'
            if canonical in spellings and spellings[canonical] != original:
                raise ArchiveRejected('Имена ZIP конфликтуют по регистру или Unicode')
            if canonical in types and types[canonical] != desired:
                raise ArchiveRejected('Файл и каталог ZIP конфликтуют')
            spellings[canonical], types[canonical] = original, desired
            if i == len(parts):
                if canonical in explicit:
                    raise ArchiveRejected('Повторяющийся путь внутри ZIP')
                explicit.add(canonical)
    return {'entries': len(entries), 'files': files, 'uncompressed_bytes': total}
