"""The isolated legacy-only schema and simulated backup-before-application startup."""
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from storage import legacy_startup_schema, playback_migration


class LegacyStartupSchemaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.path = self.root / 'library.db'
        self.backups = self.root / 'backups'; self.backups.mkdir()
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.addCleanup(self.db.close)
        self.db.execute('create table items(id integer primary key, title, author, topic, kind, path, root, url unique, size int, added default current_timestamp)')
        self.db.execute('create table progress(slug primary key, cid, page int)')
        self.db.execute("insert into items(id,title,kind,url,path,root) values(1,'Old game','game','game:old','','')")
        self.db.execute("insert into progress values('old','4',83)")
        self.db.commit()

    def migrate(self):
        return playback_migration.migrate(self.db, self.backups, initialize=legacy_startup_schema.initialize,
                                          needs=legacy_startup_schema.requires_migration)

    def test_snapshot_precedes_old_schema_only_and_repeat_is_noop(self):
        snapshot = self.migrate()
        with closing(sqlite3.connect(snapshot)) as before:
            self.assertEqual(before.execute('select page from progress').fetchone()[0], 83)
            self.assertNotIn('thumb', [r[1] for r in before.execute('pragma table_info(items)')])
            self.assertIsNone(before.execute("select name from sqlite_master where name='inbox'").fetchone())
        self.assertFalse(legacy_startup_schema.requires_migration(self.db))
        self.assertIsNone(self.db.execute("select name from sqlite_master where name='playpos'").fetchone())
        self.assertNotIn('updated', [r['name'] for r in self.db.execute('pragma table_info(progress)')])
        self.assertIsNone(self.migrate())
        self.assertEqual(len(list(self.backups.glob('*.db'))), 1)
        self.assertEqual(self.db.execute('select title from items').fetchone()[0], 'Old game')

    def test_incomplete_or_foreign_schema_rolls_back(self):
        self.db.execute('create table inbox(id integer primary key)'); self.db.commit()
        before = list(self.db.iterdump())
        with self.assertRaises(sqlite3.DatabaseError): self.migrate()
        self.assertEqual(list(self.db.iterdump()), before)
        self.assertEqual(len(list(self.backups.glob('*.db'))), 1)
        self.assertFalse(self.db.in_transaction)

    def test_failed_snapshot_and_partial_schema_do_not_mutate(self):
        before = list(self.db.iterdump())
        with patch.object(playback_migration.os, 'link', side_effect=OSError('failure')):
            with self.assertRaises(playback_migration.BackupError): self.migrate()
        self.assertEqual(list(self.db.iterdump()), before)
        def broken(db):
            db.execute('create table partial_change(id)')
            raise sqlite3.OperationalError('failure')
        with patch.object(legacy_startup_schema.database, 'initialize', side_effect=broken):
            with self.assertRaises(sqlite3.OperationalError): self.migrate()
        self.assertEqual(list(self.db.iterdump()), before)
        self.assertEqual(len(list(self.backups.glob('*.db'))), 1)

    def test_simulated_backup_failure_prevents_application_import(self):
        before = list(self.db.iterdump())
        code = r'''
import sqlite3
from unittest.mock import patch
from storage import database, legacy_startup_schema, playback_migration
from pathlib import Path
import os
root = Path(os.environ['MEDIAHUB_DATA_DIR'])
def guarded(path):
    db = sqlite3.connect(path); db.row_factory = sqlite3.Row
    try:
        with patch.object(playback_migration.os, 'link', side_effect=OSError('failure')):
            playback_migration.migrate(db, root / 'backups', initialize=legacy_startup_schema.initialize, needs=legacy_startup_schema.requires_migration)
    finally: db.close()
    raise AssertionError('must not proceed')
database.open_database = guarded
try:
    from legacy import app
except playback_migration.BackupError:
    pass
else:
    raise AssertionError('application unexpectedly initialized')
'''
        result = subprocess.run([sys.executable, '-c', code], env=dict(os.environ, MEDIAHUB_DATA_DIR=str(self.root)),
                                capture_output=True, text=True, timeout=40)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(list(self.db.iterdump()), before)
        self.assertFalse(list(self.backups.glob('*.db')))

    def test_real_app_after_guarded_start_has_no_further_schema_changes(self):
        self.db.close()
        code = r'''
import http.client, json, sqlite3, threading
from pathlib import Path
from core.local_http import LocalHTTPServer
from storage import database, legacy_startup_schema, playback_migration
root = Path(__import__('os').environ['MEDIAHUB_DATA_DIR']); backup = root / 'backups'
original = database.open_database
versions = []
def guarded(path):
    db = sqlite3.connect(path); db.row_factory = sqlite3.Row
    try:
        snapshot = playback_migration.migrate(db, backup, initialize=legacy_startup_schema.initialize, needs=legacy_startup_schema.requires_migration)
        versions.append(db.execute('pragma schema_version').fetchone()[0])
    finally: db.close()
    conn, lock = original(path)
    assert conn.execute('pragma schema_version').fetchone()[0] == versions[0]
    return conn, lock
database.open_database = guarded
from legacy import app
assert app.sql('pragma schema_version')[0][0] == versions[0]
assert not legacy_startup_schema.requires_migration(app.db)
assert len(list(backup.glob('*.db'))) == 1
assert app.sql("select page from progress where slug='old'")[0][0] == 83
assert app.db.execute("select name from sqlite_master where name='playpos'").fetchone() is None
server = LocalHTTPServer(('127.0.0.1', 0), app.H); thread = threading.Thread(target=server.serve_forever); thread.start()
try:
    c = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
    c.request('GET', '/api/library'); response = c.getresponse(); rows = json.loads(response.read()); c.close()
    assert response.status == 200 and rows[0]['title'] == 'Old game'
finally:
    server.shutdown(); server.server_close(); thread.join(); app.db.close()
'''
        try:
            for _ in range(2):
                result = subprocess.run([sys.executable, '-c', code], env=dict(os.environ, MEDIAHUB_DATA_DIR=str(self.root)),
                                        capture_output=True, text=True, timeout=40)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(len(list(self.backups.glob('*.db'))), 1)
            with closing(sqlite3.connect(next(self.backups.glob('*.db')))) as old:
                self.assertEqual(old.execute('select page from progress').fetchone()[0], 83)
                self.assertNotIn('thumb', [r[1] for r in old.execute('pragma table_info(items)')])
        finally:
            self.db = sqlite3.connect(self.path); self.db.row_factory = sqlite3.Row
            self.addCleanup(self.db.close)
