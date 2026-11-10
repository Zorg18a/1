"""Timestamped reader writes on temporary, explicitly migrated SQLite databases."""
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

from core.reader_progress import validate_progress
from storage import playback_migration, reader_progress, startup_schema
from storage.database import open_database


class ReaderProgressStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db, self.lock = open_database(self.root / 'library.db')
        self.db.execute("insert into items(id,kind,title,url,path,root) values "
                        "(1,'manga','Manga','manga:old','p','r'),"
                        "(2,'video','Video','video:test','p','r'),"
                        "(3,'manga','Bad','manga:','p','r'),"
                        "(4,'manga','Wrong prefix','other:old','p','r')")
        self.db.execute("insert into progress(slug,cid,page) values('old','1',9)")
        self.db.commit()
        self.backups = self.root / 'backups'
        self.backups.mkdir()

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def migrate(self):
        return playback_migration.migrate(self.db, self.backups,
                                          initialize=startup_schema.initialize,
                                          needs=startup_schema.requires_migration)

    def save(self, item_id, chapter, page):
        return reader_progress.save_progress(self.db, self.lock, item_id, chapter, page)

    def row(self):
        return tuple(self.db.execute("select cid,page,updated from progress where slug='old'").fetchone())

    def test_backup_old_rows_update_and_reopen(self):
        snapshot = self.migrate()
        with closing(sqlite3.connect(snapshot)) as backup:
            self.assertEqual(backup.execute("select cid,page from progress where slug='old'").fetchone(), ('1', 9))
            self.assertNotIn('updated', [row[1] for row in backup.execute('pragma table_info(progress)')])
        self.assertEqual(self.row(), ('1', 9, None))
        with patch('storage.reader_progress.time.time', side_effect=[1000.0, 1001.0]):
            self.assertTrue(self.save(1, '12', 0))
            self.assertEqual(self.row(), ('12', 0, 1000.0))
            self.assertTrue(self.save(1, 13, 10))
            self.assertEqual(self.row(), ('13', 10, 1001.0))
        self.db.close()
        self.db, self.lock = open_database(self.root / 'library.db')
        self.assertEqual(self.row(), ('13', 10, 1001.0))
        self.assertIsNone(self.migrate())

    def test_missing_wrong_kind_bad_url_and_deleted_item_do_not_create_rows(self):
        self.migrate()
        for item_id in (2, 3, 4, 999):
            with self.subTest(item_id=item_id):
                self.assertFalse(self.save(item_id, '12', 1))
        self.db.execute('delete from items where id=1')
        self.db.commit()
        self.assertFalse(self.save(1, '12', 1))
        self.assertEqual(self.row(), ('1', 9, None))
        self.assertEqual(self.db.execute('select count(*) from progress').fetchone()[0], 1)

    def test_validation_rejects_bad_input_without_writes(self):
        self.migrate()
        cases = [(0, '1', 0), (True, '1', 0), (2**63, '1', 0),
                 (1, '', 0), (1, '-1', 0), (1, '١', 0), (1, '1' * 31, 0),
                 (1, True, 0), (1, 1.0, 0), (1, '1', -1),
                 (1, '1', True), (1, '1', 1.5), (1, '1', 2**63)]
        for arguments in cases:
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                self.save(*arguments)
        self.assertEqual(self.row(), ('1', 9, None))
        self.assertEqual(validate_progress(1, '0' * 30, 0), (1, '0' * 30, 0))

    def test_write_error_rolls_back_and_existing_transaction_is_not_committed(self):
        self.migrate()
        self.db.execute("create trigger deny_progress before update on progress begin select raise(abort, 'denied'); end")
        self.db.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            self.save(1, '12', 4)
        self.assertFalse(self.db.in_transaction)
        self.assertEqual(self.row(), ('1', 9, None))
        self.db.execute("update items set title='uncommitted' where id=1")
        with self.assertRaises(ValueError):
            self.save(1, '12', 4)
        self.assertTrue(self.db.in_transaction)
        self.db.rollback()
        self.assertEqual(self.db.execute('select title from items where id=1').fetchone()[0], 'Manga')

    def test_upsert_preserves_unrelated_columns(self):
        self.migrate()
        self.db.execute("alter table progress add column custom text default 'initial'")
        self.db.execute("update progress set custom='keep' where slug='old'")
        self.db.commit()
        self.assertTrue(self.save(1, '20', 5))
        self.assertEqual(self.db.execute("select custom from progress where slug='old'").fetchone()[0], 'keep')

    def test_unmigrated_database_is_not_modified(self):
        before = list(self.db.iterdump())
        with self.assertRaises(sqlite3.OperationalError):
            self.save(1, '12', 3)
        self.assertFalse(self.db.in_transaction)
        self.assertEqual(list(self.db.iterdump()), before)

    def test_concurrent_saves_are_serialized_and_complete(self):
        self.migrate()
        errors = []
        def save(n):
            try:
                if not self.save(1, str(n), n):
                    errors.append('missing')
            except Exception as exc:
                errors.append(str(exc))
        threads = [threading.Thread(target=save, args=(n,)) for n in range(20)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        cid, page, updated = self.row()
        self.assertEqual(int(cid), page)
        self.assertGreater(updated, 0)
        self.assertEqual(self.db.execute('pragma integrity_check').fetchone()[0], 'ok')

    def test_existing_reader_can_read_saved_values_without_timestamp(self):
        chapter = self.root / 'manga' / 'chapters' / '12'
        chapter.mkdir(parents=True)
        (chapter / '001.png').write_bytes(b'PNG')
        manifest = {'slug': 'old', 'title': 'Manga', 'listed': [{'cid': '12', 'label': 'Chapter'}],
                    'chapters': {'12': {'label': 'Chapter', 'files': ['001.png'], 'expected': 1, 'done': True}}}
        (self.root / 'manga' / 'manifest.json').write_text(json.dumps(manifest), encoding='utf8')
        self.db.execute('update items set root=?,path=? where id=1',
                        (str(self.root / 'manga'), str(chapter / '001.png')))
        self.db.commit()
        self.migrate()
        self.save(1, '12', 0)
        self.db.close()
        code = '''
import http.client, json, threading
from http.server import ThreadingHTTPServer
from legacy import app
server = ThreadingHTTPServer(('127.0.0.1', 0), app.H)
thread = threading.Thread(target=server.serve_forever); thread.start()
try:
    conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
    conn.request('GET', '/api/manga/1'); response = conn.getresponse()
    assert response.status == 200
    assert json.loads(response.read())['progress'] == {'cid': '12', 'page': 0}
    # Legacy route still replaces the row and discards updated: integration is not done.
    body = json.dumps({'id': 1, 'cid': '12', 'page': 1})
    conn.request('POST', '/api/progress', body, {'X-MH': '1', 'Content-Type': 'application/json'})
    response = conn.getresponse(); assert response.status == 200; response.read()
    assert app.sql("select updated from progress where slug='old'")[0]['updated'] is None
    conn.close()
finally:
    server.shutdown(); server.server_close(); thread.join(); app.db.close()
'''
        try:
            subprocess.run([sys.executable, '-c', code], check=True, timeout=30,
                           env=dict(os.environ, MEDIAHUB_DATA_DIR=str(self.root)))
        finally:
            self.db, self.lock = open_database(self.root / 'library.db')
