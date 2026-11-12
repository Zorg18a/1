"""Snapshot sequencing and failure behavior with a simulated file pin."""
from contextlib import closing, contextmanager
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from storage import guarded_read, guarded_snapshot, playback_migration, windows_backup_pin


class GuardedSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.source = self.root / 'source.db'
        with closing(sqlite3.connect(self.source)) as db:
            db.execute('create table example(value)')
            db.execute("insert into example values('keep')")
            db.commit()
        self.backups = self.root / 'backups'; self.backups.mkdir()
        self.guard = object()

    @contextmanager
    def pin(self, guard, name, fd):
        self.assertIs(guard, self.guard)
        self.assertTrue((self.backups / name).is_file())
        os.fstat(fd)
        yield

    def copy(self):
        return guarded_snapshot.copy_snapshot(self.source, self.backups, 5, self.guard)

    def test_snapshot_published_and_partial_retained_as_same_file(self):
        before = self.source.read_bytes()
        with patch.object(windows_backup_pin, 'pin_created_file', side_effect=self.pin):
            snapshot = self.copy()
        partial = snapshot.with_suffix('.partial')
        self.assertTrue(partial.exists())
        self.assertTrue(os.path.samefile(snapshot, partial))
        with closing(sqlite3.connect(snapshot)) as db:
            self.assertEqual(db.execute('select value from example').fetchone()[0], 'keep')
            self.assertEqual(db.execute('pragma integrity_check').fetchone()[0], 'ok')
        self.assertEqual(self.source.read_bytes(), before)

    def test_failed_pin_keeps_partial_and_publishes_nothing(self):
        before = self.source.read_bytes()
        with patch.object(windows_backup_pin, 'pin_created_file', side_effect=guarded_read.GuardedReadError('changed')):
            with self.assertRaises(playback_migration.BackupError): self.copy()
        self.assertEqual(len(list(self.backups.glob('*.partial'))), 1)
        self.assertFalse(list(self.backups.glob('*.db')))
        self.assertEqual(self.source.read_bytes(), before)

    def test_failed_copy_and_fsync_leave_partial_and_no_final(self):
        for target in ('_write_snapshot',):
            with self.subTest(target=target), patch.object(windows_backup_pin, 'pin_created_file', side_effect=self.pin), \
                 patch.object(playback_migration, target, side_effect=OSError('copy error')):
                with self.assertRaises(playback_migration.BackupError): self.copy()
        with patch.object(windows_backup_pin, 'pin_created_file', side_effect=self.pin), \
             patch.object(playback_migration.os, 'fsync', side_effect=OSError('fsync error')):
            with self.assertRaises(playback_migration.BackupError): self.copy()
        self.assertEqual(len(list(self.backups.glob('*.partial'))), 2)
        self.assertFalse(list(self.backups.glob('*.db')))

    def test_collision_never_overwrites_existing_destination(self):
        original = os.link
        def collide(src, dst):
            Path(dst).write_bytes(b'other')
            return original(src, dst)
        with patch.object(windows_backup_pin, 'pin_created_file', side_effect=self.pin), \
             patch.object(guarded_snapshot.os, 'link', side_effect=collide):
            with self.assertRaises(playback_migration.BackupError): self.copy()
        self.assertEqual(next(self.backups.glob('*.db')).read_bytes(), b'other')
        self.assertEqual(len(list(self.backups.glob('*.partial'))), 1)
