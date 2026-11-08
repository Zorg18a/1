"""Exercise extension error acknowledgements against an isolated HTTP server."""
import os
import subprocess
import sys
import tempfile
import unittest


class ExtensionErrorTests(unittest.TestCase):
    def test_failed_tab_closes_and_rejected_pairing(self):
        code = '''
import http.client, json, threading
from http.server import ThreadingHTTPServer
from legacy import app

server = ThreadingHTTPServer(('127.0.0.1', 0), app.H)
thread = threading.Thread(target=server.serve_forever)
thread.start()

def post(path, data, headers=None):
    conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
    try:
        conn.request('POST', path, json.dumps(data), headers or {})
        response = conn.getresponse()
        body = response.read()
        return response.status, json.loads(body) if body.startswith(b'{') else None
    finally:
        conn.close()

try:
    origin = 'chrome-extension://extension-test'
    ext = {'Origin': origin}
    control = {'X-MH': '1'}
    assert post('/ext/ack', {'id': 1, 'result': 'closed'}, ext)[0] == 401
    assert post('/ext/hello', {'name': 'Test'}, ext)[1]['status'] == 'pending'
    assert post('/api/ext/approve', {'origin': origin, 'allow': False}, control)[0] == 200
    assert post('/ext/hello', {'name': 'Test'}, ext)[1]['status'] == 'pending'
    assert post('/api/ext/approve', {'origin': origin, 'allow': True}, control)[0] == 200
    ext['X-MH-Token'] = post('/ext/hello', {}, ext)[1]['token']
    for index, result in enumerate(('cancelled', 'moved', 'failed')):
        batch, count = app.inbox_add([{'id': index, 'url': 'https://example.org/' + result}], True, 'test')
        assert count == 1
        row = app.sql('select id from inbox where batch=?', (batch,))[0]
        app.inbox_confirm({'batch': batch, 'close': True, 'rows': [{'id': row['id'], 'action': 'link'}]})
        assert post('/ext/ack', {'id': row['id'], 'result': result}, ext)[0] == 200
        row = app.sql('select status,cmd,reason from inbox where id=?', (row['id'],))[0]
        assert row['status'] == 'kept' and row['cmd'] == '' and row['reason']
finally:
    server.shutdown()
    server.server_close()
    thread.join()
    app.db.close()
'''
        with tempfile.TemporaryDirectory() as directory:
            env = dict(os.environ, MEDIAHUB_DATA_DIR=directory)
            subprocess.run([sys.executable, '-c', code], env=env, check=True, timeout=30)
