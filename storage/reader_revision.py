"""Experimental revision-fenced reader storage. Not used by the application.

Install only inside an explicit, backup-first migration transaction. All cooperating
writers must retain the triggers and revision tombstones; schema tampering is outside
this module's protection. Tokens are random 128-bit values, not timestamps.
"""
import re
import sqlite3

from core.legacy_reader_progress import _integer

_TABLE = 'mediahub_reader_revision'
_TOKEN = 'lower(hex(randomblob(16)))'


def _trigger(name, event, table, expression, condition):
    return (f'CREATE TRIGGER {name} AFTER {event} ON {table} WHEN {condition} BEGIN '
            f'INSERT INTO {_TABLE}(slug,token) VALUES ({expression},{_TOKEN}) '
            f'ON CONFLICT(slug) DO UPDATE SET token={_TOKEN}; END')


def _triggers():
    result = {}
    for event, aliases in (('INSERT', ('new',)), ('UPDATE', ('old', 'new')), ('DELETE', ('old',))):
        for alias in aliases:
            name = f'mediahub_reader_progress_{event.lower()}_{alias}'
            slug = f'{alias}.slug'
            result[name] = _trigger(name, event, 'progress', slug,
                                    f"typeof({slug})='text' AND length({slug})>0")
            name = f'mediahub_reader_item_{event.lower()}_{alias}'
            url = f'{alias}.url'
            result[name] = _trigger(name, event, 'items', f'substr({url},7)',
                                    f"{alias}.kind='manga' AND typeof({url})='text' "
                                    f"AND substr({url},1,6)='manga:' AND length({url})>6")
    return result


def initialize(db):
    """Create isolated revision state inside a transaction; never silently replace objects."""
    if not db.in_transaction:
        raise ValueError('Необходима транзакция миграции')
    for table, required, primary in (('items', {'id', 'kind', 'url'}, 'id'),
                                     ('progress', {'slug', 'cid', 'page'}, 'slug')):
        rows = db.execute(f'pragma table_info({table})').fetchall()
        columns = {r[1]: r for r in rows}
        if not required.issubset(columns) or columns[primary][5] != 1 or sum(bool(r[5]) for r in rows) != 1:
            raise sqlite3.DatabaseError(f'Несовместимая таблица {table}')
    names = [_TABLE, *_triggers()]
    if any(db.execute('select 1 from sqlite_master where lower(name)=lower(?)', (name,)).fetchone() for name in names):
        raise sqlite3.DatabaseError('Объекты ревизий уже существуют; миграция отменена')
    db.execute(f'CREATE TABLE {_TABLE}(slug TEXT PRIMARY KEY NOT NULL, token TEXT NOT NULL)')
    db.execute(f"INSERT INTO {_TABLE}(slug,token) SELECT slug,{_TOKEN} FROM progress "
               "WHERE typeof(slug)='text' AND length(slug)>0")
    db.execute(f"INSERT OR IGNORE INTO {_TABLE}(slug,token) SELECT substr(url,7),{_TOKEN} FROM items "
               "WHERE kind='manga' AND typeof(url)='text' AND substr(url,1,6)='manga:' AND length(url)>6")
    for sql in _triggers().values():
        db.execute(sql)


def _validate(db):
    columns = {r[1]: r for r in db.execute(f'pragma table_info({_TABLE})')}
    if (set(columns) != {'slug', 'token'} or columns['slug'][2].upper() != 'TEXT'
            or columns['slug'][5] != 1 or not columns['slug'][3]
            or columns['token'][2].upper() != 'TEXT' or not columns['token'][3]):
        raise sqlite3.DatabaseError('Несовместимая таблица ревизий')
    for name, expected in _triggers().items():
        row = db.execute("select sql from sqlite_master where type='trigger' and name=?", (name,)).fetchone()
        if not row or row[0] != expected:
            raise sqlite3.DatabaseError('Отсутствует или изменён триггер ревизий')


class Conflict(Exception):
    """Item identity or progress changed since the caller's snapshot."""


def _item(db, item_id):
    row = db.execute("select substr(url,7) from items where id=? and kind='manga' "
                     "and typeof(url)='text' and substr(url,1,6)='manga:' and length(url)>6", (item_id,)).fetchone()
    return row[0] if row else None


def _snapshot(db, slug):
    token = db.execute(f'select token from {_TABLE} where slug=?', (slug,)).fetchone()
    if not token or not isinstance(token[0], str) or not re.fullmatch(r'[0-9a-f]{32}', token[0]):
        raise sqlite3.DatabaseError('Отсутствует или повреждена ревизия манги')
    progress = db.execute('select cid,page from progress where slug=?', (slug,)).fetchone()
    return {'slug': slug, 'token': token[0], 'progress': {'cid': progress[0], 'page': progress[1]} if progress else None}


def _transaction(db, lock, action, immediate=False):
    with lock:
        if db.in_transaction:
            raise RuntimeError('A transaction is already in progress')
        try:
            db.execute('begin immediate' if immediate else 'begin')
            _validate(db)
            result = action()
            db.commit()
            return result
        except BaseException:
            db.rollback()
            raise


def read(db, lock, item_id):
    item_id = _integer(item_id, 1)
    def action():
        slug = _item(db, item_id)
        return _snapshot(db, slug) if slug is not None else None
    return _transaction(db, lock, action)


def write(db, lock, item_id, expected_slug, expected_token, chapter, page):
    """Compare and write atomically; raise Conflict instead of overwriting a newer write."""
    item_id, page = _integer(item_id, 1), _integer(page, 0)
    if (not isinstance(expected_slug, str) or not expected_slug or
            not isinstance(expected_token, str) or not re.fullmatch(r'[0-9a-f]{32}', expected_token) or
            not isinstance(chapter, str) or not chapter or len(chapter) > 1024):
        raise ValueError('Некорректные данные позиции или ревизии')
    def action():
        slug = _item(db, item_id)
        if slug != expected_slug or _snapshot(db, slug)['token'] != expected_token:
            raise Conflict('Позиция или материал изменились')
        columns = {row[1] for row in db.execute('pragma table_info(progress)')}
        reset = ',updated=NULL' if 'updated' in columns else ''
        db.execute("insert into progress(slug,cid,page) values(?,?,?) on conflict(slug) "
                   "do update set cid=excluded.cid,page=excluded.page" + reset, (slug, chapter, page))
        return _snapshot(db, slug)
    return _transaction(db, lock, action, immediate=True)
