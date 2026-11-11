"""Revision fencing experiment; temporary databases only, not wired to the app."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

from storage import legacy_reader_progress, playback_migration, reader_revision
from storage.database import open_database


class ReaderRevisionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = self.root / 'library.db'
        self.db, self.lock = open_database(self.path)
        self.db.execute("insert into items(id,kind,url) values(1,'manga','manga:alpha')")
        self.db.execute("insert into progress values('alpha','old',3)")
        self.db.commit()
        self.backups = self.root / 'backups'
        self.backups.mkdir()

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def migrate(self):
        return playback_migration.migrate(self.db, self.backups, initialize=reader_revision.initialize)

    def read(self):
        return reader_revision.read(self.db, self.lock, 1)

    def write(self, snapshot, cid='new', page=4):
        return reader_revision.write(self.db, self.lock, 1, snapshot['slug'], snapshot['token'], cid, page)

    def test_backup_old_data_and_reopen(self):
        snapshot_path = self.migrate()
        with closing(sqlite3.connect(snapshot_path)) as backup:
            self.assertEqual(backup.execute('select cid,page from progress').fetchone(), ('old', 3))
            self.assertIsNone(backup.execute("select name from sqlite_master where name='mediahub_reader_revision'").fetchone())
        before = self.read()
        result = self.write(before)
        self.assertNotEqual(before['token'], result['token'])
        self.assertEqual(result['progress'], {'cid': 'new', 'page': 4})
        with closing(sqlite3.connect(self.path)) as reopened:
            self.assertEqual(reader_revision.read(reopened, threading.Lock(), 1), result)
        self.assertEqual(self.db.execute('pragma integrity_check').fetchone()[0], 'ok')

    def test_two_writers_race_and_lost_response_retry(self):
        self.migrate(); snapshot = self.read(); barrier = threading.Barrier(2)
        def worker(page):
            with closing(sqlite3.connect(self.path, timeout=5)) as db:
                barrier.wait()
                try:
                    return reader_revision.write(db, threading.Lock(), 1, snapshot['slug'], snapshot['token'], 'new', page)
                except reader_revision.Conflict:
                    return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(worker, [8, 9]))
        self.assertEqual(sum(r is not None for r in results), 1)
        saved = self.read()
        self.assertIn(saved['progress']['page'], [8, 9])
        with self.assertRaises(reader_revision.Conflict):
            self.write(snapshot, 'late', 1)
        self.assertEqual(self.read(), saved)

    def test_legacy_replace_and_aba_are_fenced(self):
        self.migrate(); before = self.read()
        self.db.execute("insert or replace into progress values('alpha','intermediate',9)")
        self.db.execute("update progress set cid='old',page=3 where slug='alpha'")
        self.db.commit()
        after = self.read()
        self.assertEqual(after['progress'], before['progress'])
        self.assertNotEqual(after['token'], before['token'])
        with self.assertRaises(reader_revision.Conflict): self.write(before)

    def test_legacy_api_writer_invalidates_snapshot(self):
        self.migrate(); before = self.read()
        self.assertTrue(legacy_reader_progress.save(self.db, self.lock, 1, 'old-client', 22))
        with self.assertRaises(reader_revision.Conflict): self.write(before)
        self.assertEqual(self.read()['progress'], {'cid': 'old-client', 'page': 22})

    def test_empty_progress_creates_and_fences_delayed_request(self):
        self.db.execute("delete from progress where slug='alpha'"); self.db.commit()
        self.migrate(); empty = self.read()
        self.assertIsNone(empty['progress'])
        latest = self.write(empty, 'later', 7)
        with self.assertRaises(reader_revision.Conflict): self.write(empty, 'delayed', 1)
        self.assertEqual(self.read(), latest)

    def test_delete_recreate_progress_and_item_id(self):
        self.migrate(); before = self.read()
        self.db.execute("delete from progress where slug='alpha'")
        self.db.commit()
        empty = self.read()
        self.assertIsNone(empty['progress'])
        with self.assertRaises(reader_revision.Conflict): self.write(before)
        self.db.execute("insert into progress values('alpha','old',3)")
        self.db.execute('delete from items where id=1')
        self.db.execute("insert into items(id,kind,url) values(1,'manga','manga:alpha')")
        self.db.commit()
        with self.assertRaises(reader_revision.Conflict): self.write(empty)
        with self.assertRaises(reader_revision.Conflict): self.write(before)
        after = self.read()
        self.assertEqual(after['progress'], before['progress'])
        self.assertNotEqual(after['token'], before['token'])

    def test_changed_or_deleted_item_cannot_receive_stale_write(self):
        self.migrate(); before = self.read()
        self.db.execute("update items set url='manga:beta' where id=1"); self.db.commit()
        with self.assertRaises(reader_revision.Conflict): self.write(before)
        self.assertEqual(self.read()['slug'], 'beta')
        self.db.execute('delete from items where id=1'); self.db.commit()
        self.assertIsNone(self.read())
        with self.assertRaises(reader_revision.Conflict): self.write(before)

    def test_failed_write_rolls_back_position_and_token(self):
        self.migrate(); before = self.read()
        self.db.execute("create trigger deny_reader before update on progress begin select raise(abort, 'denied'); end")
        self.db.commit()
        with self.assertRaises(sqlite3.IntegrityError): self.write(before)
        self.assertFalse(self.db.in_transaction)
        self.assertEqual(self.read(), before)
        self.db.execute('drop trigger deny_reader'); self.db.commit()
        self.assertEqual(self.write(before)['progress']['page'], 4)

    def test_missing_or_changed_trigger_fails_closed(self):
        self.migrate(); before = self.read()
        self.db.execute('drop trigger mediahub_reader_progress_update_new'); self.db.commit()
        with self.assertRaises(sqlite3.DatabaseError): self.read()
        with self.assertRaises(sqlite3.DatabaseError): self.write(before)
        self.assertEqual(self.db.execute("select page from progress where slug='alpha'").fetchone()[0], 3)

    def test_backup_failure_and_object_conflict_do_not_migrate(self):
        with self.assertRaises(playback_migration.BackupError):
            playback_migration.migrate(self.db, self.root / 'missing', initialize=reader_revision.initialize)
        self.assertIsNone(self.db.execute("select name from sqlite_master where name='mediahub_reader_revision'").fetchone())
        self.db.execute('create table mediahub_reader_revision(other text)'); self.db.commit()
        with self.assertRaises(sqlite3.DatabaseError): self.migrate()
        self.assertEqual([r[1] for r in self.db.execute('pragma table_info(mediahub_reader_revision)')], ['other'])
        self.assertEqual(self.db.execute("select page from progress where slug='alpha'").fetchone()[0], 3)
        self.assertEqual(len(list(self.backups.glob('*.db'))), 1)

    def test_partial_ddl_failure_rolls_back_and_keeps_backup(self):
        triggers = reader_revision._triggers()
        triggers['forced_failure'] = 'CREATE TRIGGER invalid syntax'
        with patch.object(reader_revision, '_triggers', return_value=triggers):
            with self.assertRaises(sqlite3.DatabaseError): self.migrate()
        self.assertFalse(self.db.in_transaction)
        self.assertIsNone(self.db.execute("select name from sqlite_master where name='mediahub_reader_revision'").fetchone())
        self.assertEqual(self.db.execute("select count(*) from sqlite_master where name like 'mediahub_reader_%'").fetchone()[0], 0)
        self.assertEqual(self.db.execute('select page from progress').fetchone()[0], 3)
        self.assertEqual(len(list(self.backups.glob('*.db'))), 1)

    def test_invalid_values_or_missing_manga_do_not_write(self):
        self.migrate(); before = self.read()
        for cid, page in [('', 1), ('x', -1), (True, 1), ('x', 1.5)]:
            with self.assertRaises(ValueError): self.write(before, cid, page)
        for token in ('bad', None, 'a' * 31):
            with self.assertRaises(ValueError): reader_revision.write(self.db, self.lock, 1, 'alpha', token, 'x', 0)
        self.assertIsNone(reader_revision.read(self.db, self.lock, 99))
        self.assertEqual(self.read(), before)
