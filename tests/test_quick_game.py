"""Exercise the authenticated quick-game bridge without network or user data."""
import os
import subprocess
import sys
import tempfile
import unittest

from core.game_sources import game_thread_url


class GameSourceTests(unittest.TestCase):
    def test_allowed_and_rejected_urls(self):
        self.assertEqual(game_thread_url('https://f95zone.to/threads/game.123/page-2?x=1#post'),
                         'https://f95zone.to/threads/game.123/')
        for url in ('http://f95zone.to/threads/x.1', 'https://f95zone.to.evil.test/threads/1',
                    'https://user@f95zone.to/threads/1', 'https://f95zone.to:444/threads/1',
                    'https://f95zone.to/threads/x%2F1', 'https://127.0.0.1/threads/1',
                    'https://f95zone.to/threads/', 'https://f95zone.to/\nthreads/1', None, 5):
            with self.subTest(url=url):
                self.assertIsNone(game_thread_url(url))

    def test_extension_queue_and_game_card(self):
        code = '''
import http.client, json, threading
from pathlib import Path
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from legacy import app
server = ThreadingHTTPServer(('127.0.0.1', 0), app.H)
thread = threading.Thread(target=server.serve_forever)
thread.start()
def request(method, path, data=None, headers=None):
    conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
    try:
        conn.request(method, path, json.dumps(data) if data is not None else None, headers or {})
        response = conn.getresponse()
        return response.status, json.loads(response.read())
    finally:
        conn.close()
try:
    origin = 'chrome-extension://test'
    app.EXT[origin] = 'secret'
    ext = {'Origin': origin, 'X-MH-Token': 'secret'}
    endpoint = '/ext/game/add'
    assert request('POST', endpoint, {'url': 'https://f95zone.to/threads/game.123/'})[0] == 401
    assert request('POST', endpoint, {'url': 'https://127.0.0.1/threads/1'}, ext)[0] == 400
    assert request('POST', endpoint, {'url': []}, ext)[0] == 400
    assert not app.jobs
    status, result = request('POST', endpoint, {'url': 'https://f95zone.to/threads/game.123/page-2'}, ext)
    assert status == 200 and result['status'] == 'queued'
    job = app.jobs[result['job']]
    assert job['kind'] == 'gamecard' and job['url'] == 'https://f95zone.to/threads/game.123/'
    cover = Path(app.BASE) / 'fake-cover.jpg'
    cover.write_bytes(b'fixture')
    html = ('<meta property="og:title" content="Unity - Example Game [1.2] [Studio]">'
            '<meta property="og:image" content="https://f95zone.to/cover.jpg">')
    with patch.object(app, 'ext_online', return_value=True), patch.object(app, 'fetch_html', return_value=html), \\
            patch.object(app, 'fetch_cover', return_value=str(cover)) as cache:
        app.game_card(job)
    cache.assert_called_once()
    status, rows = request('GET', '/api/library')
    assert status == 200 and len(rows) == 1
    row = rows[0]
    assert row['title'] == 'Example Game' and row['g']['latest'] == '1.2'
    assert row['g']['thread'] == 'https://f95zone.to/threads/game.123/'
    assert row['thumb'] == str(cover) and row['cover']
finally:
    server.shutdown()
    server.server_close()
    thread.join()
    app.db.close()
'''
        with tempfile.TemporaryDirectory() as directory:
            env = dict(os.environ, MEDIAHUB_DATA_DIR=directory)
            subprocess.run([sys.executable, '-c', code], env=env, check=True, timeout=30)
