"""Enumerate game folders at an explicitly chosen depth; never descend into games."""
import os
import re
import stat

ARCH = ('.zip', '.rar', '.7z', '.tar', '.gz', '.tgz')
LAYOUTS = ('auto', 'flat', 'nested', 'nested2')
CATEGORY = re.compile(r'^(new|n|part|batch|vol)[ _-]?\d+$', re.I)
SKIP = {'$recycle.bin', 'system volume information', 'incoming_downloads'}


def tree_stats(top):
    """Size and newest mtime of accessible files, excluding links and reparse points."""
    total, newest, stack = 0, 0.0, [top]
    while stack:
        try:
            entries = os.scandir(stack.pop())
        except OSError:
            continue
        with entries:
            for entry in entries:
                try:
                    info = entry.stat(follow_symlinks=False)
                    if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400):
                        continue
                    if stat.S_ISDIR(info.st_mode):
                        stack.append(entry.path)
                    elif stat.S_ISREG(info.st_mode):
                        total += info.st_size
                        newest = max(newest, info.st_mtime)
                except OSError:
                    continue
    return total, newest


def list_games(root, layout='auto'):
    if layout not in LAYOUTS:
        raise ValueError('Неизвестная структура папок')
    out = []

    def visit(folder, depth):
        # A failed category read aborts the scan instead of returning a misleading partial list.
        with os.scandir(folder) as entries:
            for entry in sorted(entries, key=lambda e: e.name.lower()):
                lower = entry.name.lower()
                if entry.name.startswith('.') or lower.startswith('_gamesweep') or lower in SKIP:
                    continue
                info = entry.stat(follow_symlinks=False)
                if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400):
                    continue
                if stat.S_ISDIR(info.st_mode):
                    expand = ((layout == 'nested' and depth < 1) or
                              (layout == 'nested2' and depth < 2) or
                              (layout == 'auto' and depth == 0 and CATEGORY.match(entry.name)))
                    if expand:
                        visit(entry.path, depth + 1)
                    else:
                        out.append({'name': entry.name, 'path': entry.path, 'type': 'folder'})
                elif stat.S_ISREG(info.st_mode) and lower.endswith(ARCH):
                    out.append({'name': entry.name, 'path': entry.path, 'type': 'archive'})
    visit(root, 0)
    return out
