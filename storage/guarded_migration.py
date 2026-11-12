"""Experimental backup-directory guard for the isolated migration coordinator.

Only protects the existing directory chain on local Windows NTFS; it does not
secure the DB path, backup files, ACLs, external writers or power-loss durability.
The application does not invoke this function.
"""
import os

from storage import guarded_read, playback_migration


def migrate(db, backup_dir, timeout=30.0, *, initialize=None, needs=None):
    """Hold directory handles for the whole snapshot and migration transaction."""
    try:
        guard = guarded_read.open_guarded_directory(os.fspath(backup_dir))
    except (OSError, TypeError, guarded_read.GuardedReadError) as exc:
        raise playback_migration.BackupError('Не удалось защитить каталог резервной копии; миграция отменена') from exc
    with guard:
        return playback_migration.migrate(db, backup_dir, timeout, initialize=initialize, needs=needs)
