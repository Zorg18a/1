"""Experimental transactional equivalent of the existing legacy startup schema.

Not used by the application startup. Run only through a backup-first coordinator
with a trusted database and backup directory; schema checks are conservative.
"""
import sqlite3

from storage import database, schema_validation

_ITEM_ADDITIONS = ('src', 'tracked int default 0', 'checked', 'info')
_TAG_TRIGGER = ('create trigger delete_game_tags after delete on items '
                'begin delete from game_tags where item_id = old.id; end')
_REQUIRED = {
    'items': {'id', 'title', 'author', 'topic', 'kind', 'path', 'root', 'url', 'size',
              'added', 'thumb', 'src', 'tracked', 'checked', 'info'},
    'progress': {'slug', 'cid', 'page'},
    'game_tags': {'item_id', 'position', 'tag'},
    'inbox': {'id', 'batch', 'tab_id', 'window_id', 'url', 'title', 'kind', 'host',
              'action', 'state', 'lib_id', 'close_tab', 'status', 'reason', 'jobs', 'cmd', 'created'},
}


def _columns(db, table):
    return {row['name'] for row in db.execute(f'pragma table_info({table})')}


def requires_migration(db):
    """Inspect only; lock out concurrent SQLite writers through subsequent migration."""
    types = {row['name']: row['type'] for row in db.execute('select name,type from sqlite_master')}
    for table, required in _REQUIRED.items():
        if types.get(table) != 'table' or not required.issubset(_columns(db, table)):
            return True
    trigger = db.execute("select sql from sqlite_master where type='trigger' and name='delete_game_tags'").fetchone()
    if trigger is None:
        return True
    if not isinstance(trigger['sql'], str) or ' '.join(trigger['sql'].lower().split()) != _TAG_TRIGGER:
        raise sqlite3.DatabaseError('Несовместимый триггер game_tags; миграция отменена')
    schema_validation.validate(db)
    return False


def initialize(db):
    """Apply only existing legacy schema steps, within the caller's transaction."""
    if not db.in_transaction:
        raise ValueError('Для миграции необходима транзакция')
    database.initialize(db)
    columns = _columns(db, 'items')
    for declaration in _ITEM_ADDITIONS:
        if declaration.split()[0] not in columns:
            db.execute('alter table items add column ' + declaration)
    db.execute("create table if not exists inbox(id integer primary key, batch text, tab_id int, window_id int, url text, title text, kind text, host text, action text, state text, lib_id int, close_tab int, status text, reason text default '', jobs text default '[]', cmd text default '', created text default current_timestamp)")
    if requires_migration(db):
        raise sqlite3.DatabaseError('Неполная или несовместимая схема; миграция отменена')
