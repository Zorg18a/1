"""Bounded inventory of possible save files; stat only, never open file contents."""
import os
from pathlib import Path
import stat
import threading
import time

from storage.incoming_downloads import stat_identity
from storage.save_discovery import DiscoveryBusy, _check_components, _directory, _game_folder, discover_saves

MAX_ENTRIES = 5000
MAX_FILES = 200
MAX_DEPTH = 8
MAX_SECONDS = 10
MAX_PATH_BYTES = 1024
_LIMIT = threading.BoundedSemaphore(1)


def _regular(info):
    return stat.S_ISREG(info.st_mode) and not (getattr(info, 'st_file_attributes', 0) &
                                               getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400))


def inventory_saves(root, game):
    if not _LIMIT.acquire(blocking=False):
        raise DiscoveryBusy('Другой просмотр состава сохранений уже выполняется')
    try:
        preview = discover_saves(root, game, include_identity=True)
        return _inventory(root, game, preview)
    finally:
        _LIMIT.release()


def _inventory(root, game, preview):
    top = _game_folder(root, game)
    if str(top) != preview['game_folder'] or stat_identity(os.stat(top, follow_symlinks=False)) != preview['_top_identity']:
        raise ValueError('Папка игры изменилась во время поиска; повторите просмотр')
    stack = [(top / candidate['path'], candidate['kind'], candidate['identity'], 0, False)
             for candidate in reversed(preview['candidates'])]
    files, total, scanned, skipped = [], 0, 0, preview['skipped']
    incomplete = preview['incomplete']
    deadline = time.monotonic() + MAX_SECONDS
    while stack:
        if time.monotonic() > deadline or scanned >= MAX_ENTRIES or len(files) >= MAX_FILES:
            incomplete = True
            break
        path, kind, expected, depth, counted = stack.pop()
        if not counted:
            scanned += 1
        try:
            relative = path.relative_to(top)
            if '..' in relative.parts:
                raise ValueError('path outside game')
            rel = str(relative)
            if len(rel.encode('utf-8')) > MAX_PATH_BYTES:
                raise ValueError('path too long')
            _check_components(path.parent)
            info = os.stat(path, follow_symlinks=False)
            if stat_identity(info) != expected or not (_regular(info) if kind == 'file' else _directory(info)):
                raise ValueError('entry changed')
            if kind == 'file':
                files.append({'path': rel, 'size_bytes': str(info.st_size)})
                total += info.st_size
                continue
            with os.scandir(path) as entries:
                for entry in entries:
                    if time.monotonic() > deadline or scanned >= MAX_ENTRIES:
                        incomplete = True
                        break
                    scanned += 1
                    try:
                        entry.name.encode('utf-8')
                        child = os.stat(entry.path, follow_symlinks=False)
                        if _regular(child):
                            stack.append((Path(entry.path), 'file', stat_identity(child), depth + 1, True))
                        elif _directory(child) and depth < MAX_DEPTH:
                            stack.append((Path(entry.path), 'directory', stat_identity(child), depth + 1, True))
                        else:
                            incomplete, skipped = True, skipped + 1
                    except (OSError, UnicodeError):
                        incomplete, skipped = True, skipped + 1
            after = os.stat(path, follow_symlinks=False)
            if not _directory(after) or stat_identity(after) != expected:
                incomplete, skipped = True, skipped + 1
        except (OSError, ValueError, UnicodeError):
            incomplete, skipped = True, skipped + 1
    try:
        after_top = os.stat(top, follow_symlinks=False)
        if not _directory(after_top) or stat_identity(after_top) != preview['_top_identity']:
            incomplete, skipped = True, skipped + 1
    except OSError:
        incomplete, skipped = True, skipped + 1
    files.sort(key=lambda item: (item['path'].casefold(), item['path']))
    return {'game_folder': str(top), 'locations': len(preview['candidates']), 'files': files,
            'total_bytes': str(total), 'scanned': scanned, 'incomplete': incomplete, 'skipped': skipped}
