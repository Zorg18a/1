"""Fake yt-dlp exercises partial results through the queue and incoming tabs."""
import os
import subprocess
import sys
import tempfile
import unittest


class PlaylistTests(unittest.TestCase):
    def test_media_outcomes_and_tab_fate_without_network(self):
        code = '''
import json, sys, types
from legacy import app

modes = {}
class FakeYDL:
    def __init__(self, options): self.options = options
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def extract_info(self, url, download=False):
        entries = [{'url': 'https://example.org/one'}, {'url': 'https://example.org/two'}]
        if extra_entry: entries.append(None)
        return {'_type': 'playlist', 'entries': entries}
    def download(self, urls):
        url = urls[0]
        mode = modes[url.rsplit('/', 1)[-1]]
        if mode == 'exception': raise RuntimeError('network failure')
        if mode == 'logger':
            self.options['logger'].error('network failure')
            return 0
        if mode == 'return': return 1
        if mode == 'ok':
            self.options['postprocessor_hooks'][0]({'postprocessor': 'MoveFiles', 'status': 'finished',
                'info_dict': {'title': 'clip', 'filepath': 'fake.mp4', 'webpage_url': url}})
        if mode == 'cancel': current_job['cancel'] = True
        return 0
sys.modules['yt_dlp'] = types.SimpleNamespace(YoutubeDL=FakeYDL, utils=types.SimpleNamespace(DownloadCancelled=RuntimeError))
app.scan = lambda: None
app.backfill = lambda: None
app.add = lambda *args: None
app.cfg['folder'] = str(app.BASE)
app.cfg['thumbs'] = False

try:
    cases = [
        (('ok', 'ok'), False, 'готово', 'closing'),
        (('ok', 'ok'), True, 'частично', 'kept'),
        (('ok', 'exception'), False, 'частично', 'kept'),
        (('ok', 'logger'), False, 'частично', 'kept'),
        (('ok', 'return'), False, 'частично', 'kept'),
        (('exception', 'logger'), False, 'ошибка', 'kept'),
        (('skip', 'skip'), False, 'пропущено', 'kept'),
        (('ok', 'cancel'), False, 'отменено', 'kept'),
    ]
    for i, (behaviors, extra_entry, expected_status, expected_fate) in enumerate(cases):
        modes = dict(zip(('one', 'two'), behaviors))
        jid = i + 100
        current_job = {'id': jid, 'url': 'https://example.org/playlist', 'kind': 'video',
                       'res': 'best', 'afmt': 'mp3', 'topic': '', 'subs': '', 'thumbs': False,
                       'start_at': 0, 'daily': False, 'status': 'в очереди', 'pct': 0,
                       'title': 'test', 'speed': 0, 'eta': 0, 'cancel': False}
        app.jobs[jid] = current_job
        batch, _ = app.inbox_add([{'id': i, 'url': 'https://example.org/tab' + str(i)}], True, 'test')
        row = app.sql('select id from inbox where batch=?', (batch,))[0]
        app.sql("update inbox set status='queued', jobs=? where id=?", (json.dumps([jid]), row['id']))
        app.scheduler.process(current_job)
        assert current_job['status'].startswith(expected_status), (behaviors, current_job['status'])
        app.settle()
        result = app.sql('select status,cmd,reason from inbox where id=?', (row['id'],))[0]
        assert result['status'] == expected_fate, (behaviors, dict(result))
        assert result['cmd'] == ('close' if expected_fate == 'closing' else '')
        if expected_fate == 'kept': assert result['reason']
finally:
    app.db.close()
'''
        with tempfile.TemporaryDirectory() as directory:
            env = dict(os.environ, MEDIAHUB_DATA_DIR=directory)
            subprocess.run([sys.executable, '-c', code], env=env, check=True, timeout=30)
