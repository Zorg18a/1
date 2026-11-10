"""SQLite access shared by the legacy application and new modules."""
import sqlite3
import threading

from storage import game_tags
from core.search import contains


def initialize(db):
    """Initialize the base schema inside the caller's transaction."""
    db.execute('create table if not exists items(id integer primary key, title, author, topic, kind, path, root, url unique, size int, added default current_timestamp, thumb)')
    columns = {row['name'] for row in db.execute('pragma table_info(items)')}
    if 'thumb' not in columns:
        db.execute('alter table items add column thumb')
    db.execute('create table if not exists progress(slug primary key, cid, page int)')
    game_tags.initialize(db)


def open_database(path):
    db = sqlite3.connect(path, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.create_function('mh_search', 2, contains)
    initialize(db)
    db.commit()
    return db, threading.Lock()


def execute(db, lock, statement, params=()):
    with lock:
        try:
            rows = db.execute(statement, params).fetchall()
            db.commit()
            return rows
        except sqlite3.Error:
            db.rollback()
            raise
