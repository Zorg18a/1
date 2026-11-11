"""SQLite backup inspection and experimental restore to a NEW file.

Only in-memory inspect_bytes is wired to the application; file restoration is not.
Path-based operations require trusted paths and do not protect against external
replacement, reparse points, or hostile ACLs. Restore never overwrites a destination.
"""
from contextlib import closing
from dataclasses import dataclass
import math
import os
from pathlib import Path
import sqlite3
import tempfile
import time


class RestoreError(Exception):
    """Restore failed; partial, when present, is retained for inspection."""

    def __init__(self, message, partial=None):
        super().__init__(message)
        self.partial = partial


@dataclass(frozen=True)
class RestoreResult:
    path: Path
    leftover_partial: Path | None = None


def _connect_readonly(path):
    return sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=1)


def _inspect(db):
    # This is intentionally a minimum compatibility check, not full schema validation.
    db.execute('pragma trusted_schema=off')
    if db.execute('pragma integrity_check(1)').fetchall() != [('ok',)]:
        raise RestoreError('База не прошла проверку целостности')
    required = {
        'items': {'id', 'title', 'author', 'topic', 'kind', 'path', 'root', 'url', 'size', 'added'},
        'progress': {'slug', 'cid', 'page'},
    }
    counts = {}
    for table, columns in required.items():
        row = db.execute('select type,sql from sqlite_master where name=?', (table,)).fetchone()
        if not row or row[0] != 'table' or not (row[1] or '').lstrip().upper().startswith('CREATE TABLE'):
            raise RestoreError(f'В копии нет обычной таблицы {table}')
        actual = {item[1] for item in db.execute(f'pragma table_info({table})')}
        if not columns.issubset(actual):
            raise RestoreError(f'В копии несовместимая таблица {table}')
        counts[table] = db.execute(f'select count(*) from {table}').fetchone()[0]
    return counts


def inspect_backup(source):
    """Read-only integrity and minimal schema check; does not prove media files exist."""
    try:
        with closing(_connect_readonly(Path(source))) as db:
            return _inspect(db)
    except (OSError, sqlite3.Error) as exc:
        raise RestoreError('Не удалось открыть или проверить резервную копию') from exc


def inspect_bytes(data, *, timeout=30.0, max_bytes=64 * 1024 * 1024):
    """Inspect an uploaded standalone SQLite image in memory without touching live DB."""
    if not isinstance(data, bytes) or not 100 <= len(data) <= max_bytes:
        raise RestoreError('Размер файла должен быть от 100 байт до 64 МиБ')
    if data[:16] != b'SQLite format 3\0' or data[18:20] != b'\x01\x01':
        raise RestoreError('Нужна автономная копия SQLite без WAL')
    deadline = time.monotonic() + timeout
    try:
        with closing(sqlite3.connect(':memory:')) as db:
            db.execute('pragma trusted_schema=off')
            db.deserialize(data)
            db.execute('pragma query_only=on')
            db.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
            result = _inspect(db)
            if time.monotonic() > deadline:
                raise RestoreError('Превышено время проверки копии')
            return result
    except RestoreError:
        raise
    except (sqlite3.Error, AttributeError, MemoryError, OverflowError) as exc:
        raise RestoreError('Не удалось проверить файл копии') from exc


def restore_to_new_file(source, destination, timeout=30.0):
    """Copy a consistent snapshot to a new file without replacing any existing path.

    Source/destination and directory must be trusted local paths. Failed attempts may
    leave a .partial file. A successful publish uses a hard link on the same volume;
    directory durability after power loss is not guaranteed on all platforms.
    """
    if type(timeout) not in (int, float) or not 0 < timeout <= 600 or not math.isfinite(timeout):
        raise ValueError('Время ожидания должно быть от 0 до 600 секунд')
    source, destination = Path(source), Path(destination)
    if not destination.name or not destination.parent.is_dir():
        raise RestoreError('Папка назначения недоступна')
    if destination.exists() or destination.is_symlink():
        raise RestoreError('Файл назначения уже существует; перезапись запрещена')
    partial = None
    try:
        with closing(_connect_readonly(source)) as src:
            _inspect(src)
            fd, name = tempfile.mkstemp(prefix='mediahub-restore-', suffix='.partial', dir=destination.parent)
            partial = Path(name)
            os.close(fd)
            deadline = time.monotonic() + timeout
            def progress(_status, _remaining, _total):
                if time.monotonic() > deadline:
                    raise RestoreError('Превышено время копирования')
            with closing(sqlite3.connect(partial, timeout=1)) as dst:
                src.backup(dst, pages=128, progress=progress, sleep=0.05)
                if dst.execute('pragma journal_mode=delete').fetchone()[0].lower() != 'delete':
                    raise RestoreError('Не удалось создать автономную копию')
                _inspect(dst)
        with partial.open('r+b') as file:
            os.fsync(file.fileno())
        os.link(partial, destination)  # Atomic no-replace publish; fails on collisions.
    except (OSError, sqlite3.Error, RestoreError) as exc:
        raise RestoreError('Не удалось восстановить копию в новый файл; источник не перезаписан', partial) from exc
    try:
        partial.unlink()
        return RestoreResult(destination)
    except OSError:
        return RestoreResult(destination, partial)
