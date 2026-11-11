"""Local preflight HTTP access and no-write checks on temporary paths."""
import os
import subprocess
import sys
import tempfile
import unittest


class PreflightHttpTests(unittest.TestCase):
    def test_route(self):
        code = r'''
import http.client, json, os, threading
from pathlib import Path
from http.server import ThreadingHTTPServer
from legacy import app
from core.download_preflight import _busy
root = Path(os.environ['MEDIAHUB_DATA_DIR']).resolve()
folder = root / 'not-created'; app.cfg['folder'] = str(folder)
server = ThreadingHTTPServer(('127.0.0.1', 0), app.H)
t = threading.Thread(target=server.serve_forever); t.start()
def request(method, path, headers=None, body=None):
    conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
    try:
        conn.request(method, path, body=body, headers=headers or {})
        r = conn.getresponse(); return r.status, r.read()
    finally: conn.close()
try:
    assert request('GET', '/api/preflight')[0] == 404
    assert request('POST', '/api/preflight')[0] == 403
    assert request('POST', '/api/preflight', {'X-MH':'1','Host':'evil.example'})[0] == 403
    assert request('POST', '/api/preflight', {'X-MH':'1','Origin':'https://evil.example'})[0] == 403
    status, body = request('POST', '/api/preflight', {'X-MH':'1'}, b'{}')
    assert status == 400 and json.loads(body)['error']
    _busy.acquire()
    try:
        status, body = request('POST', '/api/preflight', {'X-MH':'1'})
        assert status == 409 and json.loads(body)['error']
    finally: _busy.release()
    status, body = request('POST', '/api/preflight', {'X-MH':'1', 'Origin':f'http://127.0.0.1:{server.server_port}'})
    data = json.loads(body)
    assert status == 200 and data['folder'] == str(folder) and data['directory']['state'] == 'missing'
    assert data['extension_online'] is False and not folder.exists()
    assert app.cfg['folder'] == str(folder) and not app.jobs
    import time
    app.EXT['chrome-extension://example'] = 'secret-not-returned'; app.EXT_SEEN[0] = time.time()
    app.cfg['folder'] = str(root)
    status, body = request('POST', '/api/preflight', {'X-MH':'1'})
    assert status == 200 and json.loads(body)['directory']['state'] == 'directory'
    assert json.loads(body)['extension_online'] is True and b'secret-not-returned' not in body
    assert request('GET', '/ui/download-preflight.js')[0] == 200
finally:
    server.shutdown(); server.server_close(); t.join(); app.db.close()
'''
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run([sys.executable, '-c', code], env=dict(os.environ, MEDIAHUB_DATA_DIR=directory), check=True, timeout=30)
