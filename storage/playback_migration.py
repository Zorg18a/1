"""Isolated, backup-first migration coordinator; not invoked by the app yet.

Requires a trusted local database path and backup directory. SQLite locks protect
against SQLite writers, not external replacement or tampering with files.
"""
from contextlib import closing
import math
import os
from pathlib import Path
import sqlite3
import tempfile
import time

from storage import playback


class BackupError(Exception):
    """The snapshot could not be made or verified; migration must not run."""


def _verify_snapshot(target):
    if target.execute('pragma integrity_check').fetchall() != [('ok',)]:
        raise BackupError('Резервная копия не прошла integrity_check')


def _write_snapshot(source_path, partial, timeout):
    deadline = time.monotonic() + timeout

    def progress(status, remaining, total):
        if time.monotonic() > deadline:
            raise BackupError('Превышено время создания резервной копии')

    uri = source_path.resolve().as_uri() + '?mode=ro'
    with closing(sqlite3.connect(uri, uri=True, timeout=min(timeout, 1))) as source:
        with closing(sqlite3.connect(partial, timeout=min(timeout, 1))) as target:
            source.backup(target, pages=128, progress=progress, sleep=0.05)
            if target.execute('pragma journal_mode=delete').fetchone()[0].lower() != 'delete':
                raise BackupError('Не удалось создать автономную резервную копию')
            _verify_snapshot(target)
    with partial.open('r+b') as f:
        os.fsync(f.fileno())


def _copy_snapshot(source_path, directory, timeout):
    # Exclusive creation prevents overwriting an existing backup. Failed attempts
    # remain visibly partial for inspection; only our own temporary link is removed.
    try:
        fd, name = tempfile.mkstemp(prefix='mediahub-before-playback-', suffix='.partial', dir=directory)
        os.close(fd)
    except OSError as exc:
        raise BackupError('Не удалось создать файл резервной копии; миграция отменена') from exc
    partial = Path(name)
    final = partial.with_suffix('.db')
    try:
        _write_snapshot(source_path, partial, timeout)
        # link is atomic and fails if final exists; unlike rename it cannot replace it.
        os.link(partial, final)
        partial.unlink()
        return final
    except (OSError, sqlite3.Error, BackupError) as exc:
        raise BackupError(f'Не удалось создать резервную копию; миграция отменена. '
                          f'Незавершённый файл: {partial}') from exc


def migrate(db, backup_dir, timeout=30.0, *, initialize=None, needs=None, _copy=None):
    """Snapshot then migrate atomically; returns the snapshot path, or None if current.

    Caller must have exclusive use of this connection and must not hold a transaction.
    A RESERVED write lock is held while a separate read-only connection copies the
    database, so other SQLite writers cannot alter it between snapshot and commit.
    """
    if db.in_transaction:
        raise ValueError('Перед миграцией завершите текущую транзакцию')
    if (type(timeout) not in (int, float) or timeout <= 0 or timeout > 600
            or not math.isfinite(timeout)):
        raise ValueError('Время ожидания должно быть от 0 до 600 секунд')
    if db.row_factory is not sqlite3.Row:
        raise ValueError('Миграция требует sqlite3.Row как row_factory')
    directory = Path(backup_dir)
    if not directory.is_dir():
        raise BackupError('Папка резервных копий недоступна')
    main = next((row[2] for row in db.execute('pragma database_list') if row[1] == 'main'), '')
    if not main:
        raise ValueError('Для миграции требуется файловая база SQLite')
    try:
        db.execute('begin immediate')
        if needs is not None and not needs(db):
            db.commit()
            return None
        snapshot = (_copy or _copy_snapshot)(Path(main), directory, timeout)
        (initialize or playback.initialize)(db)
        if needs is not None and needs(db):
            raise sqlite3.DatabaseError('Миграция не завершила схему')
        db.commit()
        return snapshot
    except BaseException:
        db.rollback()
        raise
