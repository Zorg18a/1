"""Limited, read-only suggestions for save locations inside a game folder."""
import os
from pathlib import Path
import re
import stat
import threading
import time

from storage.incoming_downloads import stat_identity

MAX_ENTRIES = 5000
MAX_CANDIDATES = 100
MAX_DEPTH = 8
MAX_SECONDS = 10
_SAVE_DIRS = {'save', 'saves', 'savedata', 'savegame', 'savegames'}
_SAVE_FILE = re.compile(r'(?i)\.(rpgsave|sav|save)$|^save[\w\- ]*\.(dat|rvdata2?|rxdata|json)$')
_LIMIT = threading.BoundedSemaphore(1)


class DiscoveryBusy(ValueError):
    """Another save discovery is already running."""


def _directory(info):
    return stat.S_ISDIR(info.st_mode) and not (getattr(info, 'st_file_attributes', 0) &
                                               getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400))


def _check_components(path):
    current = Path(path.anchor)
    if not _directory(os.stat(current, follow_symlinks=False)):
        raise ValueError('Корень пути недоступен или является ссылкой')
    for part in path.parts[1:]:
        current = current / part
        if not _directory(os.stat(current, follow_symlinks=False)):
            raise ValueError('Путь игры содержит ссылку, точку повторной обработки или не является папкой')


def _game_folder(root, game):
    if not root or not game or not isinstance(root, str) or not isinstance(game, str):
        raise ValueError('Не задана установленная папка игры или корень библиотеки')
    root, game = Path(os.path.abspath(root)), Path(os.path.abspath(game))
    try:
        inside = os.path.normcase(os.path.commonpath((root, game))) == os.path.normcase(str(root))
    except ValueError:
        inside = False
    if not inside or os.path.normcase(str(root)) == os.path.normcase(str(game)):
        raise ValueError('Папка игры не находится внутри текущего корня библиотеки')
    _check_components(root)
    _check_components(game)
    return game


def discover_saves(root, game, *, include_identity=False):
    if not _LIMIT.acquire(blocking=False):
        raise DiscoveryBusy('Другой поиск сохранений уже выполняется')
    try:
        return _discover(root, game, include_identity)
    finally:
        _LIMIT.release()


def _discover(root, game, include_identity=False):
    top = _game_folder(root, game)
    top_identity = stat_identity(os.stat(top, follow_symlinks=False))
    stack = [(top, 0, top_identity)]
    found, scanned, skipped, incomplete = [], 0, 0, False
    deadline = time.monotonic() + MAX_SECONDS
    while stack:
        if time.monotonic() > deadline or scanned >= MAX_ENTRIES or len(found) >= MAX_CANDIDATES:
            incomplete = True
            break
        folder, depth, expected = stack.pop()
        try:
            info = os.stat(folder, follow_symlinks=False)
            if not _directory(info) or stat_identity(info) != expected:
                incomplete, skipped = True, skipped + 1
                continue
            with os.scandir(folder) as entries:
                for entry in entries:
                    if time.monotonic() > deadline or scanned >= MAX_ENTRIES or len(found) >= MAX_CANDIDATES:
                        incomplete = True
                        break
                    scanned += 1
                    try:
                        entry.name.encode('utf-8')
                    except UnicodeEncodeError:
                        incomplete, skipped = True, skipped + 1
                        continue
                    try:
                        info = os.stat(entry.path, follow_symlinks=False)
                    except OSError:
                        incomplete, skipped = True, skipped + 1
                        continue
                    reparse = getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)
                    if stat.S_ISLNK(info.st_mode) or reparse:
                        incomplete, skipped = True, skipped + 1
                    elif stat.S_ISDIR(info.st_mode):
                        if entry.name.casefold() in _SAVE_DIRS:
                            found.append({'path': os.path.relpath(entry.path, top), 'kind': 'directory',
                                          **({'identity': stat_identity(info)} if include_identity else {})})
                        elif depth < MAX_DEPTH:
                            stack.append((Path(entry.path), depth + 1, stat_identity(info)))
                        else:
                            incomplete = True
                    elif stat.S_ISREG(info.st_mode) and _SAVE_FILE.search(entry.name):
                        found.append({'path': os.path.relpath(entry.path, top), 'kind': 'file',
                                      **({'identity': stat_identity(info)} if include_identity else {})})
                    elif not stat.S_ISREG(info.st_mode):
                        incomplete, skipped = True, skipped + 1
            after = os.stat(folder, follow_symlinks=False)
            if not _directory(after) or stat_identity(after) != expected:
                incomplete, skipped = True, skipped + 1
        except OSError:
            incomplete, skipped = True, skipped + 1
    found.sort(key=lambda item: (item['path'].casefold(), item['path']))
    return {'game_folder': str(top), 'candidates': found, 'scanned': scanned,
            'incomplete': incomplete, 'skipped': skipped,
            **({'_top_identity': top_identity} if include_identity else {})}
