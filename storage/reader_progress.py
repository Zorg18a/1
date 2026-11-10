"""Timestamped manga progress; isolated until backup-first startup is integrated."""
import sqlite3
import time

from core.reader_progress import validate_progress


def save_progress(db, lock, item_id, chapter_id, page):
    """Save zero-based progress for a manga item, or return False if unavailable.

    The caller must use the same lock for every use of this connection and leave
    transaction ownership to this operation. No manifest or file is accessed.
    """
    item_id, chapter_id, page = validate_progress(item_id, chapter_id, page)
    with lock:
        if db.in_transaction:
            raise ValueError('Перед сохранением завершите текущую транзакцию')
        try:
            cursor = db.execute(
                "insert into progress(slug,cid,page,updated) "
                "select substr(url,7),?,?,? from items "
                "where id=? and kind='manga' and typeof(url)='text' "
                "and substr(url,1,6)='manga:' and length(url)>6 "
                "on conflict(slug) do update set cid=excluded.cid, page=excluded.page, "
                "updated=excluded.updated", (chapter_id, page, time.time(), item_id))
            db.commit()
            return bool(cursor.rowcount)
        except sqlite3.Error:
            db.rollback()
            raise
