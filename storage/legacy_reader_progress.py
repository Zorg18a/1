"""Write the current reader schema without migrating it or replacing the row."""
import hmac
import sqlite3

from storage import reader_snapshot


class IdentityConflict(Exception):
    """The item key, progress snapshot, or a colliding row changed."""


def _write(db, item_id, chapter_id, page, expected_slug):
    columns = {row[1] for row in db.execute('pragma table_info(progress)')}
    # An old-style write cannot supply a trustworthy timestamp for newer readers.
    reset_timestamp = ', updated=NULL' if 'updated' in columns else ''
    return db.execute(
        "insert into progress(slug,cid,page) "
        "select substr(url,7),?,? from items where id=? and kind='manga' "
        "and typeof(url)='text' and substr(url,1,6)='manga:' and length(url)>6 "
        "and (? is null or substr(url,7)=? collate binary) "
        "on conflict(slug) do update set cid=excluded.cid, page=excluded.page" + reset_timestamp +
        " where ? is null or progress.slug=excluded.slug collate binary",
        (chapter_id, page, item_id, expected_slug, expected_slug, expected_slug)).rowcount


def _row(db, slug):
    return db.execute('select cid,page from progress where slug=? collate binary', (slug,)).fetchone()


def save(db, lock, item_id, chapter_id, page, expected_slug=None):
    with lock:
        if db.in_transaction:
            raise RuntimeError('A transaction is already in progress')
        try:
            count = _write(db, item_id, chapter_id, page, expected_slug)
            if not count and expected_slug is not None and db.execute(
                    "select 1 from items where id=? and kind='manga'", (item_id,)).fetchone():
                raise IdentityConflict('Идентификатор манги изменился')
            db.commit()
            return bool(count)
        except (sqlite3.Error, IdentityConflict):
            db.rollback()
            raise


def save_checked(db, lock, item_id, chapter_id, page, slug, expected_token):
    """Compare values and write under SQLite's write lock, without modifying schema."""
    with lock:
        if db.in_transaction:
            raise RuntimeError('A transaction is already in progress')
        try:
            db.execute('begin immediate')
            item = db.execute("select url from items where id=? and kind='manga'", (item_id,)).fetchone()
            if not item:
                db.rollback()
                return None
            if item[0] != 'manga:' + slug or not hmac.compare_digest(
                    reader_snapshot.token(item_id, slug, _row(db, slug)), expected_token):
                raise IdentityConflict('Запись или позиция манги изменились')
            if not _write(db, item_id, chapter_id, page, slug):
                raise IdentityConflict('Конфликт ключа позиции')
            item = db.execute("select url from items where id=? and kind='manga'", (item_id,)).fetchone()
            if not item or item[0] != 'manga:' + slug:
                raise IdentityConflict('Запись манги изменилась при сохранении')
            result = reader_snapshot.token(item_id, slug, _row(db, slug))
            db.commit()
            return result
        except BaseException:
            db.rollback()
            raise
