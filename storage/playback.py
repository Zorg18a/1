"""SQLite migration and transactional media playback-position storage."""
import sqlite3
import time

from core.playback import MIN_POSITION, is_finished, validate_item_id, validate_position

_CLEANUP_TRIGGER = ('create trigger mediahub_playpos_cleanup after delete on items '
                    'begin delete from playpos where item_id = old.id; end')


def initialize(db):
    """Run inside the caller's migration transaction; never discard existing data."""
    db.execute('create table if not exists playpos(item_id integer primary key, pos real not null, '
               'dur real not null default 0, updated real not null)')
    columns = {row['name']: row for row in db.execute('pragma table_info(playpos)')}
    if (not {'item_id', 'pos', 'dur', 'updated'}.issubset(columns) or
            columns['item_id']['type'].upper() != 'INTEGER' or columns['item_id']['pk'] != 1 or
            any(columns[name]['type'].upper() != 'REAL' or not columns[name]['notnull']
                for name in ('pos', 'dur', 'updated'))):
        raise sqlite3.DatabaseError('Несовместимая таблица playpos; миграция отменена')
    progress = {row['name']: row for row in db.execute('pragma table_info(progress)')}
    if 'updated' not in progress:
        db.execute('alter table progress add column updated real')
    elif progress['updated']['type'].upper() != 'REAL':
        raise sqlite3.DatabaseError('Несовместимый столбец progress.updated; миграция отменена')
    trigger = db.execute("select sql from sqlite_master where type='trigger' and name='mediahub_playpos_cleanup'").fetchone()
    if trigger is None:
        db.execute(_CLEANUP_TRIGGER)
    elif ' '.join(trigger['sql'].lower().split()) != _CLEANUP_TRIGGER.lower():
        raise sqlite3.DatabaseError('Несовместимый триггер playpos; миграция отменена')


def save_position(db, lock, item_id, pos, dur):
    """Return 'saved', 'ignored' (<5 seconds) or 'missing' (not video/audio)."""
    validate_item_id(item_id)
    pos, dur = validate_position(pos, dur)
    with lock:
        try:
            if pos < MIN_POSITION:
                exists = db.execute("select 1 from items where id=? and kind in ('video','audio')", (item_id,)).fetchone()
                return 'ignored' if exists else 'missing'
            cursor = db.execute("insert into playpos(item_id,pos,dur,updated) "
                                "select id,?,?,? from items where id=? and kind in ('video','audio') "
                                "on conflict(item_id) do update set pos=excluded.pos, dur=excluded.dur, updated=excluded.updated",
                                (pos, dur, time.time(), item_id))
            db.commit()
            return 'saved' if cursor.rowcount else 'missing'
        except sqlite3.Error:
            db.rollback()
            raise


def get_position(db, lock, item_id):
    validate_item_id(item_id)
    with lock:
        row = db.execute("select p.pos,p.dur,p.updated from playpos p join items i on i.id=p.item_id "
                         "where p.item_id=? and i.kind in ('video','audio')", (item_id,)).fetchone()
    if row is None:
        return None
    return {'pos': row['pos'], 'dur': row['dur'], 'updated': row['updated'],
            'finished': is_finished(row['pos'], row['dur'])}


def forget_position(db, lock, item_id):
    validate_item_id(item_id)
    with lock:
        try:
            cursor = db.execute('delete from playpos where item_id=?', (item_id,))
            db.commit()
            return bool(cursor.rowcount)
        except sqlite3.Error:
            db.rollback()
            raise
