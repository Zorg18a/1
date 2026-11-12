"""Rehearse the experimental startup migration on an in-memory SQLite snapshot.

The source is opened read-only and is never migrated. SQLite may use WAL sidecars;
paths and database contents must be trusted. This is not a backup or a sandbox.
"""
from contextlib import closing
import hashlib
from pathlib import Path
import sqlite3
import threading

from storage import backup_download, startup_schema


class RehearsalError(Exception):
    """The snapshot or experimental migration could not be safely rehearsed."""


def rehearse(path):
    """Return a data-free summary; no modifications are made to the source schema."""
    source = Path(path)
    try:
        with closing(sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True, timeout=1)) as db:
            db.execute('pragma trusted_schema=off')
            db.execute('pragma query_only=on')
            raw = backup_download.snapshot(db, threading.Lock())
        with closing(sqlite3.connect(':memory:')) as work:
            work.row_factory = sqlite3.Row
            work.deserialize(raw)
            work.execute('pragma trusted_schema=off')
            digest = hashlib.sha256(raw).hexdigest()
            work.execute('begin immediate')
            try:
                needed = startup_schema.requires_migration(work)
                if needed:
                    startup_schema.initialize(work)
                    if startup_schema.requires_migration(work):
                        raise sqlite3.DatabaseError('Пробная миграция не завершила схему')
            finally:
                work.rollback()
            if hashlib.sha256(work.serialize()).hexdigest() != digest:
                raise RehearsalError('Не удалось подтвердить откат пробной миграции')
        return {'snapshot_sha256': digest, 'snapshot_bytes': len(raw), 'migration_needed': needed,
                'rehearsal': 'ok', 'source_migrated': False}
    except RehearsalError:
        raise
    except (backup_download.BackupError, sqlite3.Error, OSError, ValueError, AttributeError,
            MemoryError, OverflowError) as exc:
        raise RehearsalError(f'Проверка не выполнена: {exc}') from exc
