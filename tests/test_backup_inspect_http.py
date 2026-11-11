"""Upload inspection route and auth use only throwaway data."""
import os
import subprocess
import sys
import tempfile
import unittest


class BackupInspectionHttpTests(unittest.TestCase):
    def test_upload_security_and_no_restore(self):
        code = r'''
import http.client, json, os, threading
from http.server import ThreadingHTTPServer
from legacy import app
from storage.backup_download import snapshot
app.sql("insert into items(id,title,kind,url) values(1,'Original','video','source')")
image = snapshot(app.db, app.lock)
app.sql("update items set title='Current' where id=1")
server = ThreadingHTTPServer(('127.0.0.1', 0), app.H)
t = threading.Thread(target=server.serve_forever); t.start()
def req(method, body=None, headers=None, path='/api/backup/inspect'):
    conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
    try:
        conn.request(method, path, body=body, headers=headers or {})
        response = conn.getresponse()
        return response.status, response.read()
    finally: conn.close()
try:
    headers = {'X-MH':'1', 'Content-Type':'application/octet-stream'}
    assert req('GET')[0] == 404
    assert req('POST', image)[0] == 403
    assert req('POST', image, dict(headers, Origin='https://evil.example'))[0] == 403
    assert req('POST', image, dict(headers, Host='evil.example'))[0] == 403
    assert req('POST', image, {'X-MH':'1', 'Content-Type':'text/plain'})[0] == 415
    from core.backup_download import _busy
    _busy.acquire()
    try:
        status, data = req('POST', image, headers)
        assert status == 409 and json.loads(data)['error']
    finally: _busy.release()
    assert req('POST', b'bad', headers)[0] == 413
    status, data = req('POST', b'x'*100, headers)
    assert status == 400 and json.loads(data)['error']
    status, data = req('POST', image, headers)
    assert status == 200 and json.loads(data) == {'ok':1, 'items':1, 'progress':0}
    assert app.sql('select title from items where id=1')[0]['title'] == 'Current'
    assert not app.db.in_transaction
    conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
    conn.putrequest('POST','/api/backup/inspect'); conn.putheader('X-MH','1')
    conn.putheader('Content-Type','application/octet-stream'); conn.putheader('Content-Length','67108865'); conn.endheaders()
    response = conn.getresponse(); assert response.status == 413; response.read(); conn.close()
    conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
    conn.putrequest('POST','/api/backup/inspect'); conn.putheader('X-MH','1')
    conn.putheader('Content-Type','application/octet-stream'); conn.putheader('Content-Length','120'); conn.putheader('Content-Length','120'); conn.endheaders()
    response = conn.getresponse(); assert response.status == 400; response.read(); conn.close()
finally:
    server.shutdown(); server.server_close(); t.join(); app.db.close()
'''
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run([sys.executable, '-c', code], env=dict(os.environ, MEDIAHUB_DATA_DIR=directory),
                           check=True, timeout=40)
