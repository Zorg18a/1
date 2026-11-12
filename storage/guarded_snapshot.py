"""Experimental Windows snapshot with pinned temporary name and no automatic unlink.

Requires a held directory guard and trusted source/ACLs. This is not a complete
security boundary: other writers can change file contents, SQLite source or WAL.
"""
import os
from pathlib import Path
import sqlite3
import tempfile

from storage import guarded_read, playback_migration, windows_backup_pin


def copy_snapshot(source, directory, timeout, guard):
    """Publish a verified snapshot without overwriting; retain the partial hard link."""
    try:
        fd, name = tempfile.mkstemp(prefix='mediahub-before-', suffix='.partial', dir=directory)
    except OSError as exc:
        raise playback_migration.BackupError('Не удалось создать файл копии; миграция отменена') from exc
    partial = Path(name)
    final = partial.with_suffix('.db')
    try:
        with windows_backup_pin.pin_created_file(guard, partial.name, fd):
            original_fd, fd = fd, None
            os.close(original_fd)
            playback_migration._write_snapshot(source, partial, timeout)
            os.link(partial, final)
        # The partial remains as another name for the same file. Removing by path
        # after releasing the pin could delete an unrelated replacement.
        return final
    except (OSError, sqlite3.Error, guarded_read.GuardedReadError, playback_migration.BackupError) as exc:
        raise playback_migration.BackupError(f'Не удалось создать копию; миграция отменена. '
                                             f'Возможный незавершённый файл: {partial}') from exc
    finally:
        if fd is not None:
            os.close(fd)
