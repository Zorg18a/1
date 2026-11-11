"""Actual local route and security checks against a throwaway library."""
import os
import subprocess
import sys
import tempfile
import unittest


class BackupHttpTests(unittest.TestCase):
    def test_download_and_security(self):
        code = r'''
import hashlib, http.client, json, os, sqlite3, threading
from pathlib import Path
from http.server import ThreadingHTTPServer
from legacy import app
root = Path(os.environ['MEDIAHUB_DATA_DIR'])
app.sql("insert into items(id,title,kind,url) values(1,'Тест','video','test')")
app.sql('pragma journal_mode=wal')
app.sql("update items set title='WAL data' where id=1")
server = ThreadingHTTPServer(('127.0.0.1', 0), app.H)
t = threading.Thread(target=server.serve_forever); t.start()
def request(method, path, headers=None):
    conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
    try:
        conn.request(method, path, headers=headers or {})
        response = conn.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally: conn.close()
try:
    assert request('GET', '/api/backup')[0] == 404
    assert request('POST', '/api/backup')[0] == 403
    assert request('POST', '/api/backup', {'X-MH':'1', 'Host':'evil.example'})[0] == 403
    assert request('POST', '/api/backup', {'X-MH':'1', 'Origin':'https://evil.example'})[0] == 403
    from core.backup_download import _busy
    _busy.acquire()
    try:
        status, _, body = request('POST', '/api/backup', {'X-MH':'1'})
        assert status == 409 and json.loads(body)['error']
    finally: _busy.release()
    status, headers, image = request('POST', '/api/backup', {'X-MH':'1', 'Origin':f'http://127.0.0.1:{server.server_port}'})
    assert status == 200 and headers['Content-Type'] == 'application/vnd.sqlite3'
    assert headers['Cache-Control'] == 'no-store' and headers['X-Content-Type-Options'] == 'nosniff'
    assert 'attachment' in headers['Content-Disposition'] and int(headers['Content-Length']) == len(image)
    assert headers['X-Backup-SHA256'] == hashlib.sha256(image).hexdigest()
    backup = root / 'download.db'; backup.write_bytes(image)
    db = sqlite3.connect(backup.as_uri() + '?mode=ro', uri=True)
    assert db.execute('select title from items').fetchone()[0] == 'WAL data'
    assert db.execute('pragma integrity_check').fetchone()[0] == 'ok'
    db.close()
    assert app.sql('select title from items where id=1')[0]['title'] == 'WAL data'
    print('backup HTTP, WAL and access checks passed')
finally:
    server.shutdown(); server.server_close(); t.join(); app.db.close()
'''
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run([sys.executable, '-c', code], env=dict(os.environ, MEDIAHUB_DATA_DIR=directory),
                           check=True, timeout=40)
