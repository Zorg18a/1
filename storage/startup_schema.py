"""Experimental unified startup schema; not wired into application startup.

Extends the legacy-only schema with playback storage inside a backup-first
transaction. The validation is conservative, not a proof for arbitrary databases.
"""
import sqlite3

from storage import legacy_startup_schema, playback


def requires_migration(db):
    """Read-only schema check; caller holds the write lock through migration."""
    if legacy_startup_schema.requires_migration(db):
        return True
    types = {row['name']: row['type'] for row in db.execute('select name,type from sqlite_master')}
    progress = {row['name'] for row in db.execute('pragma table_info(progress)')}
    columns = {row['name'] for row in db.execute('pragma table_info(playpos)')}
    if types.get('playpos') != 'table' or not {'item_id', 'pos', 'dur', 'updated'}.issubset(columns) or 'updated' not in progress:
        return True
    trigger = db.execute("select sql from sqlite_master where type='trigger' and name='mediahub_playpos_cleanup'").fetchone()
    if trigger is None:
        return True
    playback.validate_schema(db)
    return False


def initialize(db):
    """Apply legacy and playback steps atomically in a caller transaction."""
    if not db.in_transaction:
        raise ValueError('Для миграции необходима транзакция')
    legacy_startup_schema.initialize(db)
    playback.initialize(db)
    if requires_migration(db):
        raise sqlite3.DatabaseError('Неполная схема позиций; миграция отменена')
