from contextlib import closing
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from storage import playback_migration
from storage.database import open_database


class PlaybackMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = self.root / 'library.db'
        self.backups = self.root / 'backups'
        self.backups.mkdir()
        self.db, self.lock = open_database(self.path)
        self.db.execute("insert into items(id,kind,title,url) values(1,'video','Video','v')")
        self.db.execute("insert into progress values('slug','chapter',7)")
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def assert_old_schema(self, db):
        self.assertEqual(db.execute('select page from progress').fetchone()[0], 7)
        self.assertNotIn('updated', [r[1] for r in db.execute('pragma table_info(progress)')])
        self.assertIsNone(db.execute("select name from sqlite_master where name='playpos'").fetchone())

    def test_snapshot_precedes_migration_and_repeated_run_is_non_destructive(self):
        first = playback_migration.migrate(self.db, self.backups)
        self.assertEqual(first.suffix, '.db')
        with closing(sqlite3.connect(first)) as snapshot:
            self.assert_old_schema(snapshot)
            self.assertEqual(snapshot.execute('pragma integrity_check').fetchone()[0], 'ok')
        self.assertIn('updated', [r[1] for r in self.db.execute('pragma table_info(progress)')])
        second = playback_migration.migrate(self.db, self.backups)
        self.assertNotEqual(first, second)
        with closing(sqlite3.connect(first)) as snapshot:
            self.assert_old_schema(snapshot)
        with closing(sqlite3.connect(second)) as snapshot:
            self.assertIn('updated', [r[1] for r in snapshot.execute('pragma table_info(progress)')])
        self.assertFalse(list(self.backups.glob('*.partial')))

    def test_wal_uncheckpointed_data_is_in_snapshot(self):
        self.db.execute('pragma journal_mode=wal')
        self.db.execute('pragma wal_autocheckpoint=0')
        self.db.execute("update progress set page=42 where slug='slug'")
        self.db.commit()
        self.assertTrue(Path(str(self.path) + '-wal').exists())
        snapshot = playback_migration.migrate(self.db, self.backups)
        with closing(sqlite3.connect(snapshot)) as backup:
            self.assertEqual(backup.execute('select page from progress').fetchone()[0], 42)
            self.assertNotIn('updated', [r[1] for r in backup.execute('pragma table_info(progress)')])

    def test_write_lock_covers_snapshot_and_blocks_other_writer(self):
        original = playback_migration._copy_snapshot
        def check_locked(path, directory, timeout):
            with closing(sqlite3.connect(path, timeout=0.01)) as other:
                with self.assertRaises(sqlite3.OperationalError):
                    other.execute("update progress set page=8 where slug='slug'")
            return original(path, directory, timeout)
        with patch.object(playback_migration, '_copy_snapshot', side_effect=check_locked):
            snapshot = playback_migration.migrate(self.db, self.backups)
        with closing(sqlite3.connect(snapshot)) as backup:
            self.assert_old_schema(backup)

    def test_locked_database_fails_before_backup(self):
        with closing(sqlite3.connect(self.path)) as other:
            other.execute('begin immediate')
            self.db.execute('pragma busy_timeout=10')
            with self.assertRaises(sqlite3.OperationalError):
                playback_migration.migrate(self.db, self.backups)
            other.rollback()
        self.assertFalse(list(self.backups.iterdir()))
        self.assert_old_schema(self.db)
        self.assertFalse(self.db.in_transaction)

    def test_backup_failure_never_migrates_or_overwrites(self):
        sentinel = self.backups / 'keep.db'
        sentinel.write_bytes(b'keep')
        with patch.object(playback_migration.os, 'link', side_effect=OSError('disk error')):
            with self.assertRaises(playback_migration.BackupError):
                playback_migration.migrate(self.db, self.backups)
        self.assert_old_schema(self.db)
        self.assertFalse(self.db.in_transaction)
        self.assertEqual(sentinel.read_bytes(), b'keep')
        self.assertEqual(len(list(self.backups.glob('*.partial'))), 1)
        with patch.object(playback_migration.tempfile, 'mkstemp', side_effect=OSError('full')):
            with self.assertRaises(playback_migration.BackupError):
                playback_migration.migrate(self.db, self.backups)
        self.assert_old_schema(self.db)

    def test_failed_integrity_check_stops_migration(self):
        with patch.object(playback_migration, '_verify_snapshot', side_effect=playback_migration.BackupError('corrupt')):
            with self.assertRaises(playback_migration.BackupError):
                playback_migration.migrate(self.db, self.backups)
        self.assert_old_schema(self.db)
        self.assertEqual(len(list(self.backups.glob('*.partial'))), 1)
        self.assertFalse(list(self.backups.glob('*.db')))

    def test_destination_collision_does_not_replace_existing_file(self):
        real_link = playback_migration.os.link
        def collide(source, destination):
            Path(destination).write_bytes(b'existing backup')
            return real_link(source, destination)
        with patch.object(playback_migration.os, 'link', side_effect=collide):
            with self.assertRaises(playback_migration.BackupError):
                playback_migration.migrate(self.db, self.backups)
        existing = list(self.backups.glob('*.db'))
        self.assertEqual(len(existing), 1)
        self.assertEqual(existing[0].read_bytes(), b'existing backup')
        self.assert_old_schema(self.db)

    def test_unexpected_migration_error_rolls_back(self):
        def fail(db):
            db.execute('create table temporary_migration_work(id integer)')
            raise RuntimeError('simulated unexpected error')
        with patch.object(playback_migration.playback, 'initialize', side_effect=fail):
            with self.assertRaises(RuntimeError):
                playback_migration.migrate(self.db, self.backups)
        self.assertFalse(self.db.in_transaction)
        self.assertIsNone(self.db.execute("select name from sqlite_master where name='temporary_migration_work'").fetchone())
        self.assertEqual(len(list(self.backups.glob('*.db'))), 1)

    def test_schema_conflict_rolls_back_and_retains_backup(self):
        self.db.execute('alter table progress add column updated text')
        self.db.commit()
        with self.assertRaises(sqlite3.DatabaseError):
            playback_migration.migrate(self.db, self.backups)
        self.assertIsNone(self.db.execute("select name from sqlite_master where name='playpos'").fetchone())
        self.assertFalse(self.db.in_transaction)
        backups = list(self.backups.glob('*.db'))
        self.assertEqual(len(backups), 1)
        with closing(sqlite3.connect(backups[0])) as backup:
            self.assertEqual(backup.execute('select page from progress').fetchone()[0], 7)

    def test_rejects_bad_inputs_and_open_transaction(self):
        with self.assertRaises(playback_migration.BackupError):
            playback_migration.migrate(self.db, self.root / 'missing')
        for timeout in (0, -1, float('nan'), float('inf'), True, 10**400):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                playback_migration.migrate(self.db, self.backups, timeout=timeout)
        self.db.execute("update progress set page=99 where slug='slug'")
        with self.assertRaises(ValueError):
            playback_migration.migrate(self.db, self.backups)
        self.assertTrue(self.db.in_transaction)
        self.db.rollback()
        self.assert_old_schema(self.db)
