"""Verify an HTTP-created job reaches a real worker without external downloads."""
import os
import subprocess
import sys
import tempfile
import unittest


class QueueHttpTests(unittest.TestCase):
    def test_add_runs_in_worker(self):
        code = '''
import http.client, json, threading
from http.server import ThreadingHTTPServer
from legacy import app

finished = threading.Event()
processed = []
def fake_media(job):
    processed.append((job['kind'], job['url']))
    job['final'] = 'saved'
original_process = app.scheduler.process
def tracked_process(job):
    try:
        original_process(job)
    finally:
        finished.set()
app.media = fake_media
app.scheduler.process = tracked_process
app.cfg['workers'] = 1
app.spawn_workers()
server = ThreadingHTTPServer(('127.0.0.1', 0), app.H)
thread = threading.Thread(target=server.serve_forever)
thread.start()
try:
    conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
    conn.request('POST', '/api/add', json.dumps({'urls': 'https://example.org/video', 'kind': 'video'}),
                 {'X-MH': '1'})
    response = conn.getresponse()
    body = json.loads(response.read())
    conn.close()
    assert response.status == 200 and body['added'] == 1
    assert finished.wait(5), 'worker did not complete'
    assert processed == [('video', 'https://example.org/video')]
    job = next(iter(app.jobs.values()))
    assert job['status'] == 'saved' and job['pct'] == 100
finally:
    server.shutdown()
    server.server_close()
    thread.join()
    app.db.close()
'''
        with tempfile.TemporaryDirectory() as directory:
            env = dict(os.environ, MEDIAHUB_DATA_DIR=directory)
            subprocess.run([sys.executable, '-c', code], env=env, check=True, timeout=30)
