import math
import sqlite3
import tempfile
import unittest
from pathlib import Path

from core.playback import is_finished, validate_position
from storage import playback
from storage.database import open_database


class PlaybackStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db, self.lock = open_database(Path(self.temp.name) / 'test.db')
        self.db.execute("insert into items(id,kind,title,url) values(1,'video','Video','v'),(2,'audio','Audio','a'),(3,'manga','Manga','m')")
        self.db.execute("insert into progress values('slug','chapter',3)")
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def migrate(self):
        self.db.execute('begin')
        try:
            playback.initialize(self.db)
            self.db.commit()
        except sqlite3.Error:
            self.db.rollback()
            raise

    def test_migration_preserves_old_rows_and_is_idempotent(self):
        self.migrate()
        self.migrate()
        row = self.db.execute('select * from progress').fetchone()
        self.assertEqual((row['slug'], row['cid'], row['page'], row['updated']), ('slug', 'chapter', 3, None))
        self.assertEqual(self.db.execute('select count(*) from items').fetchone()[0], 3)
        self.assertEqual(self.db.execute('pragma integrity_check').fetchone()[0], 'ok')
        self.db.close()
        self.db, self.lock = open_database(Path(self.temp.name) / 'test.db')
        self.migrate()
        self.assertIsNone(playback.get_position(self.db, self.lock, 1))

    def test_incompatible_schema_rolls_back(self):
        self.db.execute('create table playpos(item_id text primary key, pos real)')
        self.db.commit()
        with self.assertRaises(sqlite3.DatabaseError):
            self.migrate()
        columns = {r['name'] for r in self.db.execute('pragma table_info(progress)')}
        self.assertNotIn('updated', columns)
        self.assertEqual(self.db.execute('select page from progress').fetchone()[0], 3)

    def test_migration_rolls_back_after_partial_change(self):
        self.db.execute('alter table progress add column updated text')
        self.db.commit()
        with self.assertRaises(sqlite3.DatabaseError):
            self.migrate()
        self.assertIsNone(self.db.execute("select name from sqlite_master where name='playpos'").fetchone())
        self.assertEqual(self.db.execute('select page from progress').fetchone()[0], 3)

    def test_save_resume_finish_and_forget(self):
        self.migrate()
        self.assertEqual(playback.save_position(self.db, self.lock, 1, 4.9, 100), 'ignored')
        self.assertEqual(playback.save_position(self.db, self.lock, 1, 5, 100), 'saved')
        self.assertFalse(playback.get_position(self.db, self.lock, 1)['finished'])
        self.db.close()
        self.db, self.lock = open_database(Path(self.temp.name) / 'test.db')
        self.assertEqual(playback.get_position(self.db, self.lock, 1)['pos'], 5)
        self.assertEqual(playback.save_position(self.db, self.lock, 1, 90, 100), 'saved')
        self.assertTrue(playback.get_position(self.db, self.lock, 1)['finished'])
        self.assertTrue(playback.forget_position(self.db, self.lock, 1))
        self.assertFalse(playback.forget_position(self.db, self.lock, 1))
        self.assertIsNone(playback.get_position(self.db, self.lock, 1))

    def test_missing_wrong_kind_and_delete(self):
        self.migrate()
        self.assertEqual(playback.save_position(self.db, self.lock, 3, 1, 100), 'missing')
        self.assertEqual(playback.save_position(self.db, self.lock, 999, 10, 100), 'missing')
        self.assertEqual(playback.save_position(self.db, self.lock, 2, 10, 0), 'saved')
        self.assertFalse(playback.get_position(self.db, self.lock, 2)['finished'])
        self.db.execute('delete from items where id=2')
        self.db.commit()
        self.assertEqual(self.db.execute('select count(*) from playpos').fetchone()[0], 0)

    def test_failed_write_rolls_back_without_losing_position(self):
        self.migrate()
        playback.save_position(self.db, self.lock, 1, 20, 100)
        self.db.execute("create trigger deny_playpos before update on playpos begin select raise(abort, 'denied'); end")
        self.db.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            playback.save_position(self.db, self.lock, 1, 50, 100)
        self.assertEqual(playback.get_position(self.db, self.lock, 1)['pos'], 20)
        self.assertFalse(self.db.in_transaction)

    def test_rules_reject_invalid_numbers(self):
        for value in (True, None, '5', math.inf, math.nan, -1, 10**400):
            with self.subTest(value=str(value)), self.assertRaises(ValueError):
                validate_position(value, 100)
        self.assertFalse(is_finished(100, 0))
        self.assertTrue(is_finished(5, 12))
        for item_id in (True, 0, -1, '1', 2**63):
            with self.subTest(item_id=item_id), self.assertRaises(ValueError):
                playback.get_position(self.db, self.lock, item_id)
