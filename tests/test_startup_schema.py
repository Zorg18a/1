from contextlib import closing
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from storage import playback_migration, startup_schema


class StartupSchemaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = self.root / 'library.db'
        self.backups = self.root / 'backups'
        self.backups.mkdir()
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def migrate(self):
        return playback_migration.migrate(self.db, self.backups, initialize=startup_schema.initialize,
                                          needs=startup_schema.requires_migration)

    def make_old_db(self):
        self.db.execute('create table items(id integer primary key, title, author, topic, kind, '
                        'path, root, url unique, size int, added default current_timestamp)')
        self.db.execute('create table progress(slug primary key, cid, page int)')
        self.db.execute("insert into items(id,title,kind,url,path,root) values(1,'Old manga','manga','manga:old','old-file','old-root')")
        self.db.execute("insert into progress values('old','chapter',12)")
        self.db.commit()

    def test_new_database_and_idempotent_explicit_migration(self):
        first = self.migrate()
        with closing(sqlite3.connect(first)) as snapshot:
            self.assertEqual(snapshot.execute("select count(*) from sqlite_master where type='table'").fetchone()[0], 0)
        self.db.execute("insert into items(id,title,kind,url) values(7,'Video','video','video:test')")
        self.db.execute('insert into playpos values(7,30,120,1234)')
        self.db.execute("insert into game_tags values(7,0,'tag')")
        self.db.commit()
        second = self.migrate()
        self.assertIsNone(second)
        self.assertEqual(len(list(self.backups.glob('*.db'))), 1)
        self.assertEqual(self.db.execute('select pos from playpos').fetchone()[0], 30)
        self.assertEqual(self.db.execute('select tag from game_tags').fetchone()[0], 'tag')
        self.db.execute('delete from items where id=7')
        self.db.commit()
        self.assertEqual(self.db.execute('select count(*) from playpos').fetchone()[0], 0)
        self.assertEqual(self.db.execute('select count(*) from game_tags').fetchone()[0], 0)

    def test_existing_tags_and_inbox_survive_pending_migration(self):
        self.migrate()
        self.db.execute("insert into items(id,title,kind,url) values(8,'Game','game','game:test')")
        self.db.execute("insert into game_tags values(8,0,'tag')")
        self.db.execute("insert into inbox(id,title,status) values(11,'Tab','pending')")
        self.db.execute('drop trigger mediahub_playpos_cleanup')
        self.db.execute('drop table playpos')
        self.db.commit()
        snapshot = self.migrate()
        with closing(sqlite3.connect(snapshot)) as old:
            self.assertEqual(old.execute('select tag from game_tags').fetchone()[0], 'tag')
            self.assertEqual(old.execute('select title from inbox').fetchone()[0], 'Tab')
        self.assertEqual(self.db.execute('select tag from game_tags').fetchone()[0], 'tag')
        self.assertEqual(self.db.execute('select title from inbox').fetchone()[0], 'Tab')
        self.assertFalse(startup_schema.requires_migration(self.db))

    def test_old_data_and_pre_migration_snapshot(self):
        self.make_old_db()
        snapshot = self.migrate()
        with closing(sqlite3.connect(snapshot)) as old:
            self.assertEqual(old.execute('select page from progress').fetchone()[0], 12)
            self.assertNotIn('thumb', [row[1] for row in old.execute('pragma table_info(items)')])
            self.assertNotIn('updated', [row[1] for row in old.execute('pragma table_info(progress)')])
            self.assertIsNone(old.execute("select name from sqlite_master where name='inbox'").fetchone())
        columns = {row['name'] for row in self.db.execute('pragma table_info(items)')}
        self.assertTrue({'thumb', 'src', 'tracked', 'checked', 'info'}.issubset(columns))
        progress = self.db.execute('select cid,page,updated from progress').fetchone()
        self.assertEqual(tuple(progress), ('chapter', 12, None))
        self.assertEqual(self.db.execute('select title from items').fetchone()[0], 'Old manga')
        self.assertEqual(self.db.execute('pragma integrity_check').fetchone()[0], 'ok')

    def test_failure_after_partial_ddl_rolls_back_every_step(self):
        self.make_old_db()
        with patch.object(startup_schema.playback, 'initialize', side_effect=sqlite3.DatabaseError('fail')):
            with self.assertRaises(sqlite3.DatabaseError):
                self.migrate()
        self.assertFalse(self.db.in_transaction)
        self.assertNotIn('thumb', [row['name'] for row in self.db.execute('pragma table_info(items)')])
        self.assertIsNone(self.db.execute("select name from sqlite_master where name='inbox'").fetchone())
        self.assertEqual(self.db.execute('select page from progress').fetchone()[0], 12)
        self.assertEqual(len(list(self.backups.glob('*.db'))), 1)

    def test_backup_error_prevents_all_schema_changes(self):
        self.make_old_db()
        with patch.object(playback_migration.os, 'link', side_effect=OSError('fail')):
            with self.assertRaises(playback_migration.BackupError):
                self.migrate()
        self.assertNotIn('thumb', [row['name'] for row in self.db.execute('pragma table_info(items)')])
        self.assertIsNone(self.db.execute("select name from sqlite_master where name='inbox'").fetchone())

    def test_incompatible_schema_fails_closed(self):
        self.make_old_db()
        self.db.execute('create table inbox(id integer primary key)')
        self.db.commit()
        with self.assertRaises(sqlite3.DatabaseError):
            self.migrate()
        self.assertEqual(self.db.execute('select page from progress').fetchone()[0], 12)
        self.assertNotIn('thumb', [row['name'] for row in self.db.execute('pragma table_info(items)')])
        self.assertEqual(len(list(self.backups.glob('*.db'))), 1)

    def test_missing_trigger_is_repaired_only_after_new_snapshot(self):
        self.migrate()
        self.db.execute('drop trigger mediahub_playpos_cleanup')
        self.db.commit()
        snapshot = self.migrate()
        self.assertIsNotNone(snapshot)
        self.assertEqual(len(list(self.backups.glob('*.db'))), 2)
        self.assertFalse(startup_schema.requires_migration(self.db))

    def test_wrong_existing_trigger_is_never_treated_as_current(self):
        self.migrate()
        self.db.execute('drop trigger delete_game_tags')
        self.db.execute('create trigger delete_game_tags after delete on items begin select 1; end')
        self.db.commit()
        with self.assertRaises(sqlite3.DatabaseError):
            self.migrate()
        self.assertFalse(self.db.in_transaction)
        self.assertEqual(len(list(self.backups.glob('*.db'))), 1)

    def test_requires_transaction(self):
        with self.assertRaises(ValueError):
            startup_schema.initialize(self.db)
        self.assertIsNone(self.db.execute("select name from sqlite_master where name='items'").fetchone())

    def test_migrated_old_database_remains_compatible_with_app(self):
        self.make_old_db()
        self.migrate()
        self.db.close()
        code = '''
import http.client, json, threading
from http.server import ThreadingHTTPServer
from legacy import app
server = ThreadingHTTPServer(('127.0.0.1', 0), app.H)
thread = threading.Thread(target=server.serve_forever)
thread.start()
try:
    conn = http.client.HTTPConnection('127.0.0.1', server.server_port)
    conn.request('GET', '/api/library')
    response = conn.getresponse()
    rows = json.loads(response.read())
    assert response.status == 200 and len(rows) == 1 and rows[0]['title'] == 'Old manga'
    assert app.sql('select page from progress')[0]['page'] == 12
    conn.close()
finally:
    server.shutdown(); server.server_close(); thread.join(); app.db.close()
'''
        try:
            subprocess.run([sys.executable, '-c', code], env=dict(os.environ, MEDIAHUB_DATA_DIR=str(self.root)),
                           check=True, timeout=30)
        finally:
            self.db = sqlite3.connect(self.path)
            self.db.row_factory = sqlite3.Row
