"""Verify an old database can be opened by the full application without data loss."""
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest


class MigrationTests(unittest.TestCase):
    def test_old_database_copy_through_http(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'old.db'
            with closing(sqlite3.connect(source)) as db, db:
                db.execute('create table items(id integer primary key, title, author, topic, kind, '
                           'path, root, url unique, size int, added default current_timestamp)')
                db.execute('insert into items(title,kind,path,url) values(?,?,?,?)',
                           ('Example', 'video', 'old-file.mp4', 'https://example.org/video'))
            data = Path(directory) / 'data'
            data.mkdir()
            with closing(sqlite3.connect(source)) as original, closing(sqlite3.connect(data / 'library.db')) as copy:
                original.backup(copy)
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
    assert response.status == 200, (response.status, rows)
    assert len(rows) == 1 and rows[0]['title'] == 'Example'
    assert rows[0]['path'] == 'old-file.mp4'
    conn.close()
finally:
    server.shutdown()
    server.server_close()
    thread.join()
    app.db.close()
'''
            env = dict(os.environ, MEDIAHUB_DATA_DIR=str(data))
            subprocess.run([sys.executable, '-c', code], env=env, check=True, timeout=30)
            with closing(sqlite3.connect(source)) as original:
                self.assertNotIn('thumb', [row[1] for row in original.execute('pragma table_info(items)')])
                self.assertEqual(original.execute('select count(*) from items').fetchone()[0], 1)
            with closing(sqlite3.connect(data / 'library.db')) as migrated:
                columns = [row[1] for row in migrated.execute('pragma table_info(items)')]
                self.assertTrue({'thumb', 'src', 'tracked', 'info'}.issubset(columns))
                self.assertEqual(migrated.execute('select count(*) from items').fetchone()[0], 1)
