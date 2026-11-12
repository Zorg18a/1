"""Bounded, read-only candidate search under the configured game root."""
from collections import deque
from datetime import datetime
import os
from pathlib import Path
import re
import stat
import threading
import time

from storage.incoming_downloads import ARCHIVE_EXTENSIONS, stat_identity
from storage.save_discovery import _check_components, _directory

MAX_DEPTH = 4
MAX_ENTRIES = 20000
MAX_MATCHES = 100
MAX_SECONDS = 15
_BUSY = threading.Lock()
_DATE = re.compile(r'(?i)[ _-](20\d{6})([a-z]?)$')


def _stem(name):
    for ext in sorted(ARCHIVE_EXTENSIONS, key=len, reverse=True):
        if name.lower().endswith(ext):
            return name[:-len(ext)]
    return name


def candidate_match(name, target, parse_name):
    """Names are suggestions only; a date-like suffix is not treated as a version."""
    label = _stem(name)
    expected = parse_name(target)['key']
    if len(expected) < 4:
        return None
    if parse_name(label)['key'] == expected:
        return 'название совпадает'
    match = _DATE.search(label)
    if match:
        try:
            datetime.strptime(match.group(1), '%Y%m%d')
        except ValueError:
            return None
        if parse_name(label[:match.start()])['key'] == expected:
            return 'совпадает название без суффикса, похожего на дату'
    return None


def search(root, title, parse_name):
    if not _BUSY.acquire(blocking=False):
        raise ValueError('Другой поиск игр ещё выполняется')
    try:
        return _search(root, title, parse_name)
    finally:
        _BUSY.release()


def _search(root, title, parse_name):
    if not isinstance(root, str) or not root.strip() or not os.path.isabs(root):
        raise ValueError('Укажите абсолютный путь к папке игр в настройках')
    base = Path(os.path.abspath(root))
    _check_components(base)
    queue = deque([(base, 0)])
    deadline = time.monotonic() + MAX_SECONDS
    found, scanned, incomplete, skipped = [], 0, False, 0
    while queue:
        if scanned >= MAX_ENTRIES or len(found) >= MAX_MATCHES or time.monotonic() > deadline:
            incomplete = True
            break
        folder, depth = queue.popleft()
        try:
            _check_components(folder)
            with os.scandir(folder) as entries:
                for entry in entries:
                    if scanned >= MAX_ENTRIES or len(found) >= MAX_MATCHES or time.monotonic() > deadline:
                        incomplete = True
                        break
                    scanned += 1
                    if entry.name.startswith('.') or entry.name.casefold().startswith('_gamesweep'):
                        continue
                    try:
                        info = entry.stat(follow_symlinks=False)
                        reparse = getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)
                        if stat.S_ISLNK(info.st_mode) or reparse:
                            skipped += 1
                            incomplete = True
                            continue
                        is_dir = _directory(info)
                        is_archive = stat.S_ISREG(info.st_mode) and entry.name.lower().endswith(ARCHIVE_EXTENSIONS)
                        match = candidate_match(entry.name, title, parse_name) if is_dir or is_archive else None
                        if match:
                            found.append({'path': entry.path, 'kind': 'folder' if is_dir else 'archive',
                                          'reason': match, 'identity': stat_identity(info)})
                        elif is_dir:
                            if depth + 1 < MAX_DEPTH:
                                queue.append((Path(entry.path), depth + 1))
                            else:
                                incomplete = True
                    except OSError:
                        skipped += 1
                        incomplete = True
        except OSError:
            skipped += 1
            incomplete = True
        except ValueError:
            skipped += 1
            incomplete = True
    found.sort(key=lambda c: (c['path'].casefold(), c['path']))
    return {'root': str(base), 'candidates': found, 'scanned': scanned,
            'incomplete': incomplete, 'skipped': skipped}
