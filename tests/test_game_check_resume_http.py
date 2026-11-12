"""HTTP continuation uses only server-side checkpoints and enforces local origin."""
import os
import subprocess
import sys
import tempfile
import unittest


class ResumeHttpTests(unittest.TestCase):
    def test_resume_and_conflict_through_http(self):
        code = r'''
import http.client, json, threading
from core.local_http import LocalHTTPServer
from legacy import app
app.sql("insert into items(id,title,kind,path,root,url,info) values(1,'Game','game','','','game:1',?)", (json.dumps({'meta': {'thread': 'https://example.com/1'}}),))
job = {'id': 999, 'kind': 'gamecheck', 'status': 'качается', 'cancel': False}
app.jobs[999] = job
try:
    app.game_check_batch.run(job, lambda: False, app.sql, app.ginfo, app.fetch_html, app.gamelib.parse_thread, app.apply_meta, 0)
except RuntimeError:
    job['status'] = 'ошибка: offline'
server = LocalHTTPServer(('127.0.0.1', 0), app.H)
t = threading.Thread(target=server.serve_forever); t.start()
def request(method, path, body=None, headers=None):
    conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
    try:
        conn.request(method, path, json.dumps(body) if body is not None else None, headers or {})
        response = conn.getresponse(); raw = response.read()
        return response.status, json.loads(raw) if response.status != 403 else None
    finally: conn.close()
try:
    assert request('POST','/api/game/check', {'resume': 999})[0] == 403
    assert request('POST','/api/game/check', {'resume': 999}, {'X-MH':'1', 'Origin':'https://evil.example'})[0] == 403
    status, jobs = request('GET', '/api/jobs')
    assert status == 200 and next(j for j in jobs if j['id'] == 999)['game_check']['resume']
    status, result = request('POST','/api/game/check', {'resume': 999}, {'X-MH':'1'})
    assert status == 200 and result['job'] in app.jobs
    assert request('POST','/api/game/check', {'resume': 999}, {'X-MH':'1'})[0] == 409
    assert request('POST','/api/game/check', {'resume': True}, {'X-MH':'1'})[0] == 400
finally:
    server.shutdown(); server.server_close(); t.join(); app.db.close()
'''
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run([sys.executable, '-c', code], env=dict(os.environ, MEDIAHUB_DATA_DIR=directory),
                           check=True, timeout=40)
