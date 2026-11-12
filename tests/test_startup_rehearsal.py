"""Experimental schema rehearsal only touches a bounded in-memory copy."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from storage import backup_download, backup_restore, legacy_startup_schema, playback_migration, startup_rehearsal, startup_schema


class StartupRehearsalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.path = self.root / 'библиотека.db'
        self.db = sqlite3.connect(self.path)
        self.addCleanup(self.db.close)
        self.db.execute('create table items(id integer primary key, title, author, topic, kind, path, root, url unique, size int, added default current_timestamp)')
        self.db.execute('create table progress(slug primary key, cid, page int)')
        self.db.execute("insert into items(id,title,kind,url) values(1,'Игра','game','game:one')")
        self.db.execute("insert into progress values('one','chapter',83)")
        self.db.commit()

    def schema(self):
        return list(self.db.execute('select type,name,sql from sqlite_master order by name'))

    def test_old_database_is_unchanged_and_rehearsal_rolls_back(self):
        before = self.path.read_bytes(); schema = self.schema()
        result = startup_rehearsal.rehearse(self.path)
        self.assertTrue(result['migration_needed'])
        self.assertTrue(result['legacy_migration_needed'])
        self.assertFalse(result['source_migrated'])
        self.assertEqual(result['rehearsal'], 'ok')
        image = backup_download.snapshot(self.db, threading.Lock())
        self.assertEqual(result['snapshot_sha256'], hashlib.sha256(image).hexdigest())
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.schema(), schema)
        self.assertEqual(self.db.execute('select page from progress').fetchone()[0], 83)
        self.assertEqual({p.name for p in self.root.iterdir()}, {self.path.name})

    def test_cli_reports_result_and_missing_database_without_creation(self):
        before = self.path.read_bytes()
        result = subprocess.run([sys.executable, '-m', 'scripts.check_startup_schema', str(self.path)],
                                capture_output=True, text=True, encoding='utf-8', timeout=20, env=dict(os.environ, PYTHONIOENCODING='utf-8'))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['rehearsal'], 'ok')
        self.assertEqual(self.path.read_bytes(), before)
        missing = self.root / 'missing.db'
        result = subprocess.run([sys.executable, '-m', 'scripts.check_startup_schema', str(missing)],
                                capture_output=True, text=True, encoding='utf-8', timeout=20, env=dict(os.environ, PYTHONIOENCODING='utf-8'))
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(missing.exists())

    def test_current_schema_needs_no_migration(self):
        self.db.row_factory = sqlite3.Row
        backup = self.root / 'backup'; backup.mkdir()
        playback_migration.migrate(self.db, backup, initialize=startup_schema.initialize,
                                   needs=startup_schema.requires_migration)
        before = self.path.read_bytes()
        result = startup_rehearsal.rehearse(self.path)
        self.assertFalse(result['migration_needed'])
        self.assertFalse(result['legacy_migration_needed'])
        self.assertEqual(self.path.read_bytes(), before)

    def test_legacy_ready_is_distinct_from_experimental_playback_schema(self):
        self.db.row_factory = sqlite3.Row
        backups = self.root / 'backup'; backups.mkdir()
        playback_migration.migrate(self.db, backups, initialize=legacy_startup_schema.initialize,
                                   needs=legacy_startup_schema.requires_migration)
        result = startup_rehearsal.rehearse(self.path)
        self.assertFalse(result['legacy_migration_needed'])
        self.assertTrue(result['migration_needed'])
        self.assertIsNone(self.db.execute("select name from sqlite_master where name='playpos'").fetchone())

    def test_wal_snapshot_has_committed_data(self):
        self.db.execute('pragma journal_mode=wal')
        self.db.execute('pragma wal_autocheckpoint=0')
        self.db.execute('update progress set page=99'); self.db.commit()
        actual = startup_rehearsal.rehearse(self.path)
        raw = backup_download.snapshot(self.db, threading.Lock())
        self.assertEqual(actual['snapshot_sha256'], hashlib.sha256(raw).hexdigest())
        self.assertTrue(actual['migration_needed'])
        self.assertEqual(self.db.execute('select page from progress').fetchone()[0], 99)

    def test_rehearsal_then_migrate_copy_and_restore_backup_to_new_file(self):
        before = self.path.read_bytes()
        self.assertTrue(startup_rehearsal.rehearse(self.path)['migration_needed'])
        copy = self.root / 'copy.db'; backup_restore.restore_to_new_file(self.path, copy)
        backup_dir = self.root / 'backup'; backup_dir.mkdir()
        with closing(sqlite3.connect(copy)) as work:
            work.row_factory = sqlite3.Row
            snapshot = playback_migration.migrate(work, backup_dir, initialize=startup_schema.initialize,
                                                 needs=startup_schema.requires_migration)
            self.assertFalse(startup_schema.requires_migration(work))
        restored = self.root / 'restored.db'; backup_restore.restore_to_new_file(snapshot, restored)
        with closing(sqlite3.connect(restored)) as old:
            self.assertEqual(old.execute('select title from items').fetchone()[0], 'Игра')
            self.assertEqual(old.execute('select page from progress').fetchone()[0], 83)
            self.assertNotIn('updated', [r[1] for r in old.execute('pragma table_info(progress)')])
        self.assertEqual(self.path.read_bytes(), before)

    def test_snapshot_and_schema_failures_leave_source_alone(self):
        before = self.path.read_bytes(); schema = self.schema()
        with patch.object(startup_rehearsal.backup_download, 'snapshot', side_effect=backup_download.BackupError('simulated failure')):
            with self.assertRaises(startup_rehearsal.RehearsalError): startup_rehearsal.rehearse(self.path)
        def fail(db):
            db.execute('create table temporary_work(x)')
            raise sqlite3.DatabaseError('simulated failure')
        with patch.object(startup_rehearsal.startup_schema, 'initialize', side_effect=fail):
            with self.assertRaises(startup_rehearsal.RehearsalError): startup_rehearsal.rehearse(self.path)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.schema(), schema)
        self.assertFalse(list(self.root.glob('*.partial')))

    def test_oversized_snapshot_and_exclusive_lock_fail_without_changes(self):
        before = self.path.read_bytes()
        with patch.object(backup_download, 'MAX_BYTES', 100):
            with self.assertRaises(startup_rehearsal.RehearsalError): startup_rehearsal.rehearse(self.path)
        self.db.execute('begin exclusive')
        try:
            with self.assertRaises(startup_rehearsal.RehearsalError): startup_rehearsal.rehearse(self.path)
        finally:
            self.db.rollback()
        self.assertEqual(self.path.read_bytes(), before)

    def test_incompatible_and_non_database_sources_fail_closed(self):
        self.db.execute('create table inbox(id integer primary key)'); self.db.commit()
        before = self.path.read_bytes()
        with self.assertRaises(startup_rehearsal.RehearsalError): startup_rehearsal.rehearse(self.path)
        self.assertEqual(self.path.read_bytes(), before)
        bad = self.root / 'invalid.db'; bad.write_bytes(b'not sqlite')
        for path in (bad, self.root / 'missing.db'):
            with self.assertRaises(startup_rehearsal.RehearsalError): startup_rehearsal.rehearse(path)
        self.assertFalse((self.root / 'missing.db').exists())
