"""Experimental read-only pinning of a trusted SQLite source on Windows NTFS."""
from contextlib import closing
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

from storage import backup_download, guarded_read, guarded_source, startup_rehearsal


class SourcePlatformTests(unittest.TestCase):
    @unittest.skipIf(os.name == 'nt', 'Windows NTFS is supported')
    def test_unsupported_platform_fails_closed(self):
        with self.assertRaises(guarded_read.GuardedReadUnsupported):
            with guarded_source.open_source('/tmp/missing.db'): pass
        with self.assertRaises(startup_rehearsal.RehearsalError):
            startup_rehearsal.rehearse('/tmp/missing.db', guard_source=True)


@unittest.skipUnless(os.name == 'nt', 'requires Windows NTFS')
class GuardedSourceWindowsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.path = self.root / 'База.db'
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('create table items(id integer primary key, title, author, topic, kind, path, root, url unique, size int, added default current_timestamp)')
            db.execute('create table progress(slug primary key, cid, page int)')
            db.execute("insert into progress values('old','1',83)"); db.commit()

    def test_read_only_while_database_name_and_directories_are_held(self):
        before = self.path.read_bytes()
        with guarded_source.open_source(self.path) as db:
            self.assertEqual(db.execute('select page from progress').fetchone()[0], 83)
            with self.assertRaises(sqlite3.OperationalError): db.execute('delete from progress')
            with self.assertRaises(OSError): self.path.rename(self.root / 'moved.db')
            with self.assertRaises(OSError): self.path.unlink()
            with self.assertRaises(OSError): self.root.rename(self.root.with_name(self.root.name + '-moved'))
        self.assertEqual(self.path.read_bytes(), before)
        self.path.rename(self.root / 'moved.db')

    def test_rehearsal_holds_pin_while_copying_and_cli_accepts_option(self):
        before = self.path.read_bytes()
        original = backup_download.snapshot
        def check_pin(db, lock):
            with self.assertRaises(OSError): self.path.rename(self.root / 'moved.db')
            return original(db, lock)
        with patch.object(backup_download, 'snapshot', side_effect=check_pin):
            report = startup_rehearsal.rehearse(self.path, guard_source=True)
        self.assertTrue(report['legacy_migration_needed'])
        self.assertFalse(report['source_migrated'])
        self.assertEqual(self.path.read_bytes(), before)
        result = subprocess.run([sys.executable, '-m', 'scripts.check_startup_schema', '--guard-source', str(self.path)],
                                capture_output=True, text=True, encoding='utf-8', timeout=20,
                                env=dict(os.environ, PYTHONIOENCODING='utf-8'))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['rehearsal'], 'ok')
        self.assertEqual(self.path.read_bytes(), before)

    def test_wal_snapshot_includes_committed_data(self):
        with closing(sqlite3.connect(self.path)) as writer:
            writer.execute('pragma journal_mode=wal')
            writer.execute('pragma wal_autocheckpoint=0')
            writer.execute('update progress set page=99'); writer.commit()
            with guarded_source.open_source(self.path) as db:
                raw = backup_download.snapshot(db, threading.Lock())
            with closing(sqlite3.connect(':memory:')) as snapshot:
                snapshot.deserialize(raw)
                self.assertEqual(snapshot.execute('select page from progress').fetchone()[0], 99)
            self.assertEqual(writer.execute('select page from progress').fetchone()[0], 99)

    def test_invalid_missing_or_hardlinked_sources_are_rejected(self):
        missing = self.root / 'missing.db'
        for path in ('relative.db', r'\\server\share\file.db', str(self.root / '..' / self.root.name / self.path.name), str(missing)):
            with self.subTest(path=path), self.assertRaises((guarded_read.GuardedReadError, OSError)):
                with guarded_source.open_source(path): pass
        self.assertFalse(missing.exists())
        alias = self.root / 'alias.db'; os.link(self.path, alias)
        with self.assertRaises(guarded_read.GuardedReadError):
            with guarded_source.open_source(self.path): pass
        self.assertEqual(self.path.read_bytes(), alias.read_bytes())

    def test_failure_releases_all_handles(self):
        bad = self.root / 'bad.db'; bad.write_bytes(b'not sqlite')
        with self.assertRaises(sqlite3.DatabaseError):
            with guarded_source.open_source(bad) as db: db.execute('select * from sqlite_master').fetchall()
        bad.rename(self.root / 'moved.db')
        self.assertEqual((self.root / 'moved.db').read_bytes(), b'not sqlite')

    def test_junction_directory_is_not_followed(self):
        junction = self.root / 'junction'
        result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(junction), str(self.root)], capture_output=True, text=True)
        if result.returncode: self.skipTest('junction creation unavailable: ' + result.stderr)
        try:
            with self.assertRaises(guarded_read.GuardedReadError):
                with guarded_source.open_source(junction / self.path.name): pass
        finally:
            os.rmdir(junction)
