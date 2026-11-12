"""Experimental read-only SQLite source pinned by name on Windows NTFS.

The directory chain and main DB name stay pinned until the connection closes.
This does not prevent external writes or protect journal/WAL sidecars, ACLs,
files replaced before opening, or SQLite's possible WAL sidecar operations.
"""
from contextlib import closing, contextmanager
import os
from pathlib import Path
import sqlite3

from storage import guarded_read, windows_backup_pin


@contextmanager
def open_source(path):
    """Open an existing local file read-only after pinning its directory and name."""
    if os.name != 'nt':
        raise guarded_read.GuardedReadUnsupported('Защищённый источник доступен только на Windows NTFS')
    try:
        raw = os.fspath(path)
    except TypeError as exc:
        raise guarded_read.GuardedReadError('Укажите путь к базе') from exc
    if not isinstance(raw, str) or not raw or len(raw) > 1024 or raw.endswith(('\\', '/')):
        raise guarded_read.GuardedReadError('Некорректный путь к базе')
    file = Path(raw)
    if not file.is_absolute():
        raise guarded_read.GuardedReadError('Требуется абсолютный путь к базе')
    with guarded_read.open_guarded_directory(str(file.parent)) as directory:
        with windows_backup_pin.pin_existing_file(directory, file.name):
            with closing(sqlite3.connect(file.as_uri() + '?mode=ro', uri=True, timeout=1)) as db:
                db.execute('pragma trusted_schema=off')
                db.execute('pragma query_only=on')
                yield db
