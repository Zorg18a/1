"""Experimental backup-directory guard for the isolated migration coordinator.

Pins the directory chain and partial-file name on Windows NTFS, but does not
secure the DB path, backup contents, ACLs, external writers or power-loss durability.
The application does not invoke this function.
"""
from dataclasses import dataclass
import os
from pathlib import Path

from storage import guarded_read, guarded_snapshot, playback_migration


@dataclass(frozen=True)
class MigrationResult:
    snapshot: Path
    retained_partial: Path


def migrate(db, backup_dir, timeout=30.0, *, initialize=None, needs=None):
    """Hold directory handles for the whole snapshot and migration transaction."""
    try:
        guard = guarded_read.open_guarded_directory(os.fspath(backup_dir))
    except (OSError, TypeError, guarded_read.GuardedReadError) as exc:
        raise playback_migration.BackupError('Не удалось защитить каталог резервной копии; миграция отменена') from exc
    with guard:
        def copy(source, directory, seconds):
            return guarded_snapshot.copy_snapshot(source, directory, seconds, guard)
        result = playback_migration.migrate(db, backup_dir, timeout, initialize=initialize, needs=needs, _copy=copy)
        return MigrationResult(result, result.with_suffix('.partial')) if result is not None else None
