"""Test module delivery and deny unexpected files through a temporary server."""
import os
import subprocess
import sys
import tempfile
import unittest


class UiAssetsTests(unittest.TestCase):
    def test_assets_and_restricted_paths(self):
        code = '''
import http.client, threading
from http.server import ThreadingHTTPServer
from legacy import app
server = ThreadingHTTPServer(('127.0.0.1', 0), app.H)
thread = threading.Thread(target=server.serve_forever)
thread.start()
try:
    for path in ('/ui/app.js', '/ui/backup.js', '/ui/inbox-submit.js', '/ui/preferences.js', '/ui/notifications.js', '/ui/hotkeys.js', '/ui/job-events.js', '/ui/cancel-all.js', '/ui/delete-dialog.js', '/ui/game-library.js', '/ui/game-scan-settings.js', '/ui/library-view.js', '/ui/game-tags.js', '/ui/game-update-preview.js', '/ui/save-inventory.js', '/ui/accessibility.css', '/ui/reader.js', '/ui/reader-images.js', '/ui/reader-progress.js', '/ui/reader-modes.js', '/ui/reader.css', '/ui/player.js', '/ui/player-keys.js', '/ui/player-subtitles.js', '/ui/player-progress.js', '/ui/player.css'):
        conn = http.client.HTTPConnection('127.0.0.1', server.server_port)
        conn.request('GET', path)
        response = conn.getresponse()
        expected = 'text/css' if path.endswith('.css') else 'text/javascript'
        assert response.status == 200, (path, response.status)
        assert response.getheader('Content-Type').startswith(expected), path
        assert response.read(), path
        conn.close()
    conn = http.client.HTTPConnection('127.0.0.1', server.server_port)
    conn.request('GET', '/m/1')
    response = conn.getresponse()
    page = response.read()
    assert response.status == 200 and b'/ui/reader.js' in page and b'/ui/reader.css' in page
    conn.close()
    for path in ('/ui/../legacy/app.py', '/ui/__init__.py', '/ui/%2e%2e/legacy/app.py'):
        conn = http.client.HTTPConnection('127.0.0.1', server.server_port)
        conn.request('GET', path)
        response = conn.getresponse()
        assert response.status == 404, (path, response.status)
        response.read()
        conn.close()
finally:
    server.shutdown()
    server.server_close()
    thread.join()
    app.db.close()
'''
        with tempfile.TemporaryDirectory() as directory:
            env = dict(os.environ, MEDIAHUB_DATA_DIR=directory)
            subprocess.run([sys.executable, '-c', code], env=env, check=True, timeout=30)
