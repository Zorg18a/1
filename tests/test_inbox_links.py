"""Link-only actions must not enable new playlist tracking or create jobs."""
import os
import subprocess
import sys
import tempfile
import unittest


class InboxLinksTests(unittest.TestCase):
    def test_overlapping_confirmations_are_serialized(self):
        code = '''
import threading
from legacy import app
try:
    batch, _ = app.inbox_add([{'id': 1, 'url': 'https://example.org/game'}], False, 'test')
    row = app.sql('select id from inbox where batch=?', (batch,))[0]
    choice = {'id': row['id'], 'kind': 'game', 'action': 'gamecard'}
    request = {'batch': batch, 'close': False, 'rows': [choice, choice]}
    entered, release, duplicate = threading.Event(), threading.Event(), threading.Event()
    calls, results, errors = [], [], []
    def new_job(*args, **kwargs):
        calls.append(1); entered.set()
        if len(calls) > 1: duplicate.set()
        assert release.wait(5)
        return 123
    app.new_job = new_job
    started = threading.Event()
    def confirm():
        started.set()
        try: results.append(app.inbox_confirm(request))
        except Exception as e: errors.append(e)
    first = threading.Thread(target=confirm); second = threading.Thread(target=confirm)
    first.start(); assert entered.wait(5)
    started.clear(); second.start(); assert started.wait(5)
    # While the first call is blocked, a second job must not be created.
    raced = duplicate.wait(0.2)
    release.set(); first.join(5); second.join(5)
    assert not raced and not first.is_alive() and not second.is_alive() and not errors, errors
    assert len(calls) == 1 and sorted(x['download'] for x in results) == [0, 1], (calls, results)
finally:
    app.db.close()
'''
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run([sys.executable, '-c', code], env=dict(os.environ, MEDIAHUB_DATA_DIR=directory),
                           check=True, timeout=30)

    def test_playlist_link_and_existing_tracking(self):
        code = '''
import http.client, json, threading
from http.server import ThreadingHTTPServer
from legacy import app
server = ThreadingHTTPServer(('127.0.0.1', 0), app.H)
thread = threading.Thread(target=server.serve_forever); thread.start()
try:
    urls = ['https://example.org/playlist1', 'https://example.org/playlist2']
    batch, _ = app.inbox_add([{'id': i, 'url': u} for i, u in enumerate(urls)], False, 'test')
    rows = app.sql('select * from inbox where batch=? order by id', (batch,))
    app.add_link('existing', app.classify(urls[1])['key'], urls[1], 'example.org', 1)
    def unexpected(*args, **kwargs): raise AssertionError('job should not be created')
    app.new_job = unexpected
    conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
    conn.request('POST', '/api/inbox/confirm', json.dumps({'batch': batch, 'close': False, 'rows': [
        {'id': r['id'], 'kind': 'playlist', 'action': 'link'} for r in rows]}), {'X-MH': '1'})
    response = conn.getresponse(); result = json.loads(response.read()); conn.close()
    assert response.status == 200 and result == {'download': 0, 'links': 2}, result
    for i, url in enumerate(urls):
        items = app.sql('select tracked from items where url=?', (app.classify(url)['key'],))
        assert items[0]['tracked'] == i, items[0]['tracked']
    assert all(r['status'] == 'done' and not r['cmd'] for r in app.sql('select status,cmd from inbox where batch=?', (batch,)))
finally:
    server.shutdown(); server.server_close(); thread.join()
    app.db.close()
'''
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run([sys.executable, '-c', code], env=dict(os.environ, MEDIAHUB_DATA_DIR=directory),
                           check=True, timeout=30)
