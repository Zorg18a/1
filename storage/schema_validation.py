"""Conservative checks for essential legacy SQLite schema invariants.

These checks are for the isolated backup-first startup path, not a proof that
an arbitrary historical schema is compatible or safe to migrate.
"""
import sqlite3


def _fail(table, detail):
    raise sqlite3.DatabaseError(f'Несовместимая таблица {table}: {detail}; миграция отменена')


def _columns(db, table):
    return {row['name']: row for row in db.execute(f'pragma table_info({table})')}


def _primary_key(db, table, expected):
    columns = _columns(db, table)
    actual = [row['name'] for row in sorted(columns.values(), key=lambda row: row['pk']) if row['pk']]
    if actual != list(expected):
        _fail(table, 'неверный первичный ключ')
    return columns


def _rowid_key(db, table):
    columns = _primary_key(db, table, ('id',))
    if columns['id']['type'].upper() != 'INTEGER':
        _fail(table, 'id не является INTEGER PRIMARY KEY')
    # INTEGER PRIMARY KEY DESC and WITHOUT ROWID have a separate PK index;
    # neither supplies the same auto-generated rowid semantics as legacy tables.
    if any(row['origin'] == 'pk' for row in db.execute(f'pragma index_list({table})')):
        _fail(table, 'id не связан с rowid')


def _unique_url(db):
    for index in db.execute('pragma index_list(items)'):
        if not index['unique'] or index['partial']:
            continue
        name = index['name'].replace('"', '""')
        keys = [row for row in db.execute(f'pragma index_xinfo("{name}")') if row['key']]
        if (len(keys) == 1 and keys[0]['name'] == 'url' and
                keys[0]['coll'].upper() == 'BINARY'):
            return
    _fail('items', 'отсутствует полная уникальность url с BINARY')


def validate(db):
    """Check keys used by legacy upserts, generated ids and tag replacement."""
    _rowid_key(db, 'items')
    _rowid_key(db, 'inbox')
    _unique_url(db)
    _primary_key(db, 'progress', ('slug',))
    tags = _primary_key(db, 'game_tags', ('item_id', 'position'))
    for name, expected in (('item_id', 'INTEGER'), ('position', 'INTEGER'), ('tag', 'TEXT')):
        if tags[name]['type'].upper() != expected or not tags[name]['notnull']:
            _fail('game_tags', f'неверный тип или ограничение {name}')
