"""Transactional storage for user-defined game tags."""
import sqlite3


def initialize(db):
    db.execute('create table if not exists game_tags (item_id integer not null, position integer not null, tag text not null, primary key(item_id, position))')
    db.execute('create trigger if not exists delete_game_tags after delete on items begin delete from game_tags where item_id = old.id; end')


def all_tags(db, lock):
    with lock:
        rows = db.execute('select item_id, tag from game_tags order by item_id, position').fetchall()
    result = {}
    for row in rows:
        result.setdefault(row['item_id'], []).append(row['tag'])
    return result


def has_tags(db, lock, item_id):
    with lock:
        return db.execute('select 1 from game_tags where item_id=? limit 1', (item_id,)).fetchone() is not None


def replace_tags(db, lock, item_id, tags):
    """Replace all tags atomically. Return False if this is not an existing game."""
    with lock:
        try:
            if not db.execute("select 1 from items where id=? and kind='game'", (item_id,)).fetchone():
                return False
            db.execute('delete from game_tags where item_id=?', (item_id,))
            db.executemany('insert into game_tags(item_id, position, tag) values(?,?,?)',
                           ((item_id, pos, tag) for pos, tag in enumerate(tags)))
            db.commit()
            return True
        except sqlite3.Error:
            db.rollback()
            raise
