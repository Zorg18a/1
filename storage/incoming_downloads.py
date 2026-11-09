"""Prepare and list the dedicated incoming folder; never open or alter archives."""
import hashlib
import os
from pathlib import Path
import stat

ARCHIVE_EXTENSIONS = ('.zip', '.7z', '.rar', '.tar', '.tar.gz', '.tgz')
SCAN_LIMIT = 5000


def is_incoming_path(path):
    return bool(path) and any(part.casefold() == 'incoming_downloads' for part in Path(path).parts)


def stat_identity(info):
    fields = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
    return hashlib.sha256(':'.join(map(str, fields)).encode('ascii')).hexdigest()


def incoming_folder(download_folder, game_root='', *, create=True):
    if not isinstance(download_folder, str) or not download_folder.strip():
        raise ValueError('Укажите папку загрузок в настройках')
    base = Path(download_folder).expanduser().resolve()
    if not base.is_dir():
        raise ValueError('Папка загрузок недоступна: проверьте настройки')
    incoming = base / 'Incoming_Downloads'
    if incoming.is_symlink() or incoming.resolve() != incoming:
        raise ValueError('Incoming_Downloads не должна быть ссылкой или находиться вне папки загрузок')
    if game_root:
        games = Path(game_root).expanduser().resolve()
        candidate = incoming.resolve()
        if games == candidate or games in candidate.parents or candidate in games.parents:
            raise ValueError('Папки игр и Incoming_Downloads пересекаются: выберите другую папку загрузок или игр')
    if create:
        incoming.mkdir(exist_ok=True)
    if not incoming.is_dir():
        raise ValueError('Incoming_Downloads не является папкой')
    return incoming


def list_archives(folder):
    archives = []
    truncated = False
    with os.scandir(folder) as entries:
        for count, entry in enumerate(entries, 1):
            if count > SCAN_LIMIT:
                truncated = True
                break
            if not entry.name.lower().endswith(ARCHIVE_EXTENSIONS) or not entry.is_file(follow_symlinks=False):
                continue
            info = os.stat(entry.path, follow_symlinks=False)
            if not stat.S_ISREG(info.st_mode) or getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400):
                continue
            archives.append({'name': entry.name, 'size': info.st_size, 'mtime': info.st_mtime,
                             'identity': stat_identity(info)})
    return archives, truncated
