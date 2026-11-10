"""Isolated backup inspection and non-destructive restore on temporary data."""
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from storage import backup_restore
from storage.database import open_database


class BackupRestoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'копия с пробелами.db'
        self.db, _ = open_database(self.source)
        self.addCleanup(self.db.close)
        self.db.execute("insert into items(id,title,kind,url) values(1,'Видео','video','a')")
        self.db.execute("insert into progress(slug,cid,page) values('manga','42',5)")
        self.db.commit()

    def test_restore_to_new_path_and_read_only_inspection(self):
        before = self.source.read_bytes()
        self.assertEqual(backup_restore.inspect_backup(self.source), {'items': 1, 'progress': 1})
        target = self.root / 'восстановлено.db'
        result = backup_restore.restore_to_new_file(self.source, target)
        self.assertEqual(result.path, target)
        self.assertIsNone(result.leftover_partial)
        self.assertEqual(self.source.read_bytes(), before)
        with closing(sqlite3.connect(target)) as db:
            self.assertEqual(db.execute('select title from items').fetchone()[0], 'Видео')
            self.assertEqual(db.execute('select page from progress').fetchone()[0], 5)
            self.assertEqual(db.execute('pragma integrity_check').fetchone()[0], 'ok')
            self.assertEqual(db.execute('pragma journal_mode').fetchone()[0], 'delete')
        self.assertFalse(list(self.root.glob('*.partial')))

    def test_snapshot_includes_committed_wal_not_just_main_file(self):
        self.db.execute('pragma journal_mode=wal')
        self.db.execute('pragma wal_autocheckpoint=0')
        self.db.execute("update progress set page=88 where slug='manga'")
        self.db.commit()
        self.assertTrue(Path(str(self.source) + '-wal').exists())
        target = self.root / 'restored.db'
        backup_restore.restore_to_new_file(self.source, target)
        with closing(sqlite3.connect(target)) as db:
            self.assertEqual(db.execute('select page from progress').fetchone()[0], 88)
            self.assertEqual(db.execute('pragma journal_mode').fetchone()[0], 'delete')

    def test_never_replaces_existing_path_including_source(self):
        existing = self.root / 'existing.db'
        existing.write_bytes(b'user data')
        for destination in (existing, self.source):
            with self.subTest(destination=destination), self.assertRaises(backup_restore.RestoreError):
                backup_restore.restore_to_new_file(self.source, destination)
        self.assertEqual(existing.read_bytes(), b'user data')
        self.assertEqual(self.db.execute('select count(*) from items').fetchone()[0], 1)
        self.assertFalse(list(self.root.glob('*.partial')))

    def test_collision_at_publish_preserves_existing_and_partial(self):
        target = self.root / 'collision.db'
        real_link = backup_restore.os.link
        def collide(partial, destination):
            Path(destination).write_bytes(b'other data')
            return real_link(partial, destination)
        with patch.object(backup_restore.os, 'link', side_effect=collide):
            with self.assertRaises(backup_restore.RestoreError) as error:
                backup_restore.restore_to_new_file(self.source, target)
        self.assertEqual(target.read_bytes(), b'other data')
        self.assertTrue(error.exception.partial.is_file())
        self.assertEqual(backup_restore.inspect_backup(error.exception.partial)['items'], 1)

    def test_failure_before_publish_retains_partial_and_leaves_target_absent(self):
        target = self.root / 'failed.db'
        with patch.object(backup_restore.os, 'fsync', side_effect=OSError('disk full')):
            with self.assertRaises(backup_restore.RestoreError) as error:
                backup_restore.restore_to_new_file(self.source, target)
        self.assertFalse(target.exists())
        self.assertTrue(error.exception.partial.is_file())
        self.assertEqual(self.db.execute('select page from progress').fetchone()[0], 5)

    def test_failure_to_unlink_published_partial_is_reported(self):
        target = self.root / 'ok.db'
        with patch.object(Path, 'unlink', side_effect=OSError('sharing violation')):
            result = backup_restore.restore_to_new_file(self.source, target)
        self.assertEqual(result.path, target)
        self.assertTrue(result.leftover_partial.exists())
        self.assertEqual(backup_restore.inspect_backup(target)['items'], 1)

    def test_corrupt_or_incompatible_sources_cannot_publish(self):
        bad = self.root / 'bad.db'
        bad.write_bytes(b'not sqlite')
        invalid = self.root / 'other.db'
        with closing(sqlite3.connect(invalid)) as db:
            db.execute('create table other(id integer)')
        for source in (bad, invalid, self.root / 'missing.db'):
            with self.subTest(source=source):
                with self.assertRaises(backup_restore.RestoreError):
                    backup_restore.inspect_backup(source)
                target = self.root / (source.stem + '-out.db')
                with self.assertRaises(backup_restore.RestoreError):
                    backup_restore.restore_to_new_file(source, target)
                self.assertFalse(target.exists())

    def test_rechecks_copied_snapshot_before_publish(self):
        target = self.root / 'unchecked.db'
        original = backup_restore._inspect
        calls = []
        def fail_after_copy(db):
            calls.append(True)
            if len(calls) == 2:
                raise backup_restore.RestoreError('simulated invalid copy')
            return original(db)
        with patch.object(backup_restore, '_inspect', side_effect=fail_after_copy):
            with self.assertRaises(backup_restore.RestoreError) as error:
                backup_restore.restore_to_new_file(self.source, target)
        self.assertEqual(len(calls), 2)
        self.assertFalse(target.exists())
        self.assertTrue(error.exception.partial.exists())

    def test_copy_timeout_fails_without_publishing(self):
        target = self.root / 'timeout.db'
        with patch.object(backup_restore.time, 'monotonic', side_effect=[1, 1000]):
            with self.assertRaises(backup_restore.RestoreError) as error:
                backup_restore.restore_to_new_file(self.source, target, timeout=1)
        self.assertFalse(target.exists())
        self.assertTrue(error.exception.partial.exists())
        self.assertEqual(self.db.execute('select page from progress').fetchone()[0], 5)

    def test_locked_source_and_create_failure_do_not_publish(self):
        target = self.root / 'locked.db'
        with closing(sqlite3.connect(self.source)) as other:
            other.execute('begin exclusive')
            with self.assertRaises(backup_restore.RestoreError):
                backup_restore.restore_to_new_file(self.source, target)
            other.rollback()
        self.assertFalse(target.exists())
        with patch.object(backup_restore.tempfile, 'mkstemp', side_effect=OSError('disk full')):
            with self.assertRaises(backup_restore.RestoreError) as error:
                backup_restore.restore_to_new_file(self.source, target)
        self.assertIsNone(error.exception.partial)
        self.assertFalse(target.exists())
        self.assertFalse(list(self.root.glob('*.partial')))

    def test_bad_inputs_fail_before_creating_partial(self):
        for timeout in (0, -1, True, float('nan'), float('inf'), 10**400):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                backup_restore.restore_to_new_file(self.source, self.root / 'out.db', timeout)
        with self.assertRaises(backup_restore.RestoreError):
            backup_restore.restore_to_new_file(self.source, self.root / 'missing' / 'out.db')
        self.assertFalse(list(self.root.glob('*.partial')))
