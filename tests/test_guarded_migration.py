"""Experimental migration directory guard, only on temporary data."""
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from storage import guarded_migration, guarded_read, legacy_startup_schema, playback_migration


class GuardedMigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.backups = self.root / 'backups'; self.backups.mkdir()
        self.path = self.root / 'library.db'
        self.db = sqlite3.connect(self.path); self.db.row_factory = sqlite3.Row
        self.addCleanup(self.db.close)
        self.db.execute('create table items(id integer primary key, title, author, topic, kind, path, root, url unique, size int, added default current_timestamp)')
        self.db.execute('create table progress(slug primary key, cid, page int)')
        self.db.execute("insert into progress values('old','1',83)"); self.db.commit()

    def migrate(self, directory=None):
        return guarded_migration.migrate(self.db, self.backups if directory is None else directory,
                                         initialize=legacy_startup_schema.initialize,
                                         needs=legacy_startup_schema.requires_migration)

    def test_refusal_happens_before_any_transaction_or_schema_change(self):
        before = list(self.db.iterdump())
        with patch.object(guarded_read, 'open_guarded_directory', side_effect=guarded_read.GuardedReadError('denied')):
            with self.assertRaises(playback_migration.BackupError): self.migrate()
        self.assertFalse(self.db.in_transaction)
        self.assertEqual(list(self.db.iterdump()), before)
        self.assertEqual(list(self.backups.iterdir()), [])

    def test_guard_wraps_snapshot_transaction_and_releases_on_failure(self):
        state = []
        class Guard:
            def __enter__(self): state.append('held'); return self
            def __exit__(self, *_): state.append('released')
        def copy(*_args):
            self.assertEqual(state, ['held'])
            raise playback_migration.BackupError('simulated failure')
        with patch.object(guarded_read, 'open_guarded_directory', return_value=Guard()), \
             patch.object(playback_migration, '_copy_snapshot', side_effect=copy):
            with self.assertRaises(playback_migration.BackupError): self.migrate()
        self.assertEqual(state, ['held', 'released'])
        self.assertFalse(self.db.in_transaction)
        self.assertNotIn('thumb', [row['name'] for row in self.db.execute('pragma table_info(items)')])

    @unittest.skipIf(os.name == 'nt', 'Windows supports guarded directories')
    def test_unsupported_platform_fails_closed(self):
        with self.assertRaises(playback_migration.BackupError): self.migrate()
        self.assertEqual(list(self.backups.iterdir()), [])

    @unittest.skipUnless(os.name == 'nt', 'requires Windows NTFS')
    def test_snapshot_while_directory_is_guarded_and_release_afterwards(self):
        original = playback_migration._copy_snapshot
        def check_held(source, directory, timeout):
            with self.assertRaises(OSError): self.backups.rename(self.root / 'moved')
            with self.assertRaises(OSError): self.root.rename(self.root.with_name(self.root.name + '-moved'))
            return original(source, directory, timeout)
        with patch.object(playback_migration, '_copy_snapshot', side_effect=check_held):
            snapshot = self.migrate()
        with closing(sqlite3.connect(snapshot)) as before:
            self.assertEqual(before.execute('select page from progress').fetchone()[0], 83)
            self.assertNotIn('thumb', [r[1] for r in before.execute('pragma table_info(items)')])
        self.assertFalse(legacy_startup_schema.requires_migration(self.db))
        self.assertIsNone(self.migrate())
        moved = self.root / 'moved'; self.backups.rename(moved)
        self.assertTrue((moved / snapshot.name).is_file())

    @unittest.skipUnless(os.name == 'nt', 'requires Windows NTFS')
    def test_access_denied_releases_directory_handles_and_keeps_database(self):
        real_open = guarded_read._nt_open_relative
        def deny(parent, name, *, directory):
            if name == self.backups.name:
                raise PermissionError('simulated access denied')
            return real_open(parent, name, directory=directory)
        before = list(self.db.iterdump())
        with patch.object(guarded_read, '_nt_open_relative', side_effect=deny):
            with self.assertRaises(playback_migration.BackupError): self.migrate()
        self.assertEqual(list(self.db.iterdump()), before)
        self.assertEqual(list(self.backups.iterdir()), [])
        self.backups.rename(self.root / 'renamed')

    @unittest.skipUnless(os.name == 'nt', 'requires Windows junctions')
    def test_junction_and_invalid_roots_are_refused_before_backup(self):
        junction = self.root / 'junction'
        proc = subprocess.run(['cmd', '/c', 'mklink', '/J', str(junction), str(self.backups)],
                              capture_output=True, text=True)
        if proc.returncode: self.skipTest('junction creation unavailable: ' + proc.stderr)
        try:
            for directory in (str(junction), str(junction / '..' / 'backups'), 'relative', r'\\server\share', r'\\?\C:\Games'):
                with self.subTest(directory=directory), self.assertRaises(playback_migration.BackupError): self.migrate(directory)
            self.assertEqual(list(self.backups.iterdir()), [])
            self.assertNotIn('thumb', [row['name'] for row in self.db.execute('pragma table_info(items)')])
        finally:
            os.rmdir(junction)
