"""Partial or failed jobs must not trigger a browser-tab close command."""
from html.parser import HTMLParser
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class CloseCheckbox(HTMLParser):
    def __init__(self):
        super().__init__()
        self.attrs = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'input' and attrs.get('id') == 'close':
            self.attrs = attrs


class InboxPartialTests(unittest.TestCase):
    def test_extension_close_is_opt_in(self):
        root = Path(__file__).resolve().parents[1]
        for folder in ('extension', 'extension-firefox'):
            parser = CloseCheckbox()
            parser.feed((root / folder / 'popup.html').read_text(encoding='utf8'))
            self.assertIsNotNone(parser.attrs)
            self.assertEqual(parser.attrs.get('type'), 'checkbox')
            self.assertNotIn('checked', parser.attrs)

    def test_partial_errors_and_success_have_correct_tab_fate(self):
        code = '''
import json
from legacy import app
try:
    cases = [('частично: 2 из 3', 'kept', ''),
             ('сохранено частично: достигнут лимит', 'kept', ''),
             ('ошибка: сеть', 'kept', ''), ('отменено', 'kept', ''),
             ('готово', 'closing', 'close'), ('сохранено', 'closing', 'close')]
    for i, (status, expected, command) in enumerate(cases):
        batch, _ = app.inbox_add([{'id': i, 'url': 'https://example.org/' + str(i)}], True, 'test')
        row = app.sql('select id from inbox where batch=?', (batch,))[0]
        jid = 100 + i
        app.jobs[jid] = {'status': status}
        app.sql("update inbox set status='queued', jobs=? where id=?", (json.dumps([jid]), row['id']))
        app.settle()
        result = app.sql('select status,cmd,reason from inbox where id=?', (row['id'],))[0]
        assert (result['status'], result['cmd']) == (expected, command), (status, dict(result))
        if 'частично' in status: assert 'частично' in result['reason']
    batch, _ = app.inbox_add([{'id': 77, 'url': 'https://example.org/restart'}], True, 'test')
    row = app.sql('select id from inbox where batch=?', (batch,))[0]
    app.sql("insert into items(title,kind,path,url) values('file','video',?,?)", (str(app.BASE), 'https://example.org/restart'))
    app.sql("update inbox set status='queued', jobs=? where id=?", (json.dumps([999]), row['id']))
    app.settle()
    result = app.sql('select status,cmd,reason from inbox where id=?', (row['id'],))[0]
    assert result['status'] == 'kept' and result['cmd'] == '' and 'неизвестен' in result['reason']
finally:
    app.db.close()
'''
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run([sys.executable, '-c', code], env=dict(os.environ, MEDIAHUB_DATA_DIR=directory),
                           check=True, timeout=30)
