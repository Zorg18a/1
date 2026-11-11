"""Write the current reader schema without migrating it or replacing the row."""
import sqlite3


class IdentityConflict(Exception):
    """The item now refers to another manga slug."""


def save(db, lock, item_id, chapter_id, page, expected_slug=None):
    with lock:
        if db.in_transaction:
            raise RuntimeError('A transaction is already in progress')
        try:
            columns = {row[1] for row in db.execute('pragma table_info(progress)')}
            # An old-style write cannot supply a trustworthy timestamp for newer readers.
            reset_timestamp = ', updated=NULL' if 'updated' in columns else ''
            cursor = db.execute(
                "insert into progress(slug,cid,page) "
                "select substr(url,7),?,? from items where id=? and kind='manga' "
                "and typeof(url)='text' and substr(url,1,6)='manga:' and length(url)>6 "
                "and (? is null or substr(url,7)=? collate binary) "
                "on conflict(slug) do update set cid=excluded.cid, page=excluded.page" + reset_timestamp +
                " where ? is null or progress.slug=excluded.slug collate binary",
                (chapter_id, page, item_id, expected_slug, expected_slug, expected_slug))
            if not cursor.rowcount and expected_slug is not None and db.execute(
                    "select 1 from items where id=? and kind='manga'", (item_id,)).fetchone():
                raise IdentityConflict('Идентификатор манги изменился')
            db.commit()
            return bool(cursor.rowcount)
        except (sqlite3.Error, IdentityConflict):
            db.rollback()
            raise
