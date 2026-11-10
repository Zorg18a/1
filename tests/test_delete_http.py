"""Deletion is tested only on temporary records and files."""
import os
import subprocess
import sys
import tempfile
import unittest


class DeleteHttpTests(unittest.TestCase):
    def test_confirmation_and_partial_failure(self):
        code = '''
import http.client, json, threading
from pathlib import Path
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from legacy import app

root = Path(app.BASE) / 'files'
root.mkdir()
video = root / 'sample.mp4'
side = root / 'sample.en.srt'
other = root / 'other.mp4'
for file in (video, side, other): file.write_text('data', encoding='utf8')
app.sql("insert into items(id,title,kind,path,root,url) values(1,'Video','video',?,'','video')", (str(video),))
server = ThreadingHTTPServer(('127.0.0.1', 0), app.H)
thread = threading.Thread(target=server.serve_forever); thread.start()
def post(payload):
    conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
    conn.request('POST', '/api/delete', json.dumps(payload), {'X-MH': '1'})
    response = conn.getresponse(); status = response.status; data = json.loads(response.read()); conn.close()
    return status, data
expected = {'title': 'Video', 'kind': 'video', 'path': str(video), 'root': ''}
try:
    assert post({'id': 1, 'files': True})[0] == 400
    assert post({'id': 1, 'files': True, 'expected': dict(expected, path='outdated')})[0] == 409
    assert post({'id': 1, 'files': False, 'expected': dict(expected, title='outdated')})[0] == 409
    assert video.exists() and side.exists() and app.sql('select id from items where id=1')
    def partial(row):
        video.unlink()
        raise OSError('simulated I/O failure')
    with patch.object(app.delete_files, 'remove_files', side_effect=partial):
        status, result = post({'id': 1, 'files': True, 'expected': expected})
    assert status == 500 and 'Часть' in result['error']
    assert not video.exists() and side.exists() and app.sql('select id from items where id=1')
    video.write_text('data', encoding='utf8')
    status, data = post({'id': 1, 'files': True, 'expected': expected})
    assert (status, data) == (200, {'ok': 1})
    assert not video.exists() and not side.exists() and other.exists()
    assert not app.sql('select id from items where id=1')
    assert post({'id': 1, 'files': False})[0] == 404
    app.sql("insert into items(id,title,kind,path,root,url) values(2,'Keep','video',?,'','keep')", (str(other),))
    assert post({'id': 2, 'files': False}) == (200, {'ok': 1})
    assert other.exists()
    folder = root / 'site'; folder.mkdir(); (folder / 'page.html').write_text('test', encoding='utf8')
    app.sql("insert into items(id,title,kind,path,root,url) values(3,'Site','site',?,?,'site')", (str(folder / 'page.html'), str(folder)))
    expected = {'title': 'Site', 'kind': 'site', 'path': str(folder / 'page.html'), 'root': str(folder)}
    assert post({'id': 3, 'files': True, 'expected': expected}) == (200, {'ok': 1})
    assert not folder.exists() and other.exists()
    app.sql("insert into items(id,title,kind,path,root,url) values(4,'Game','game',?,'','game')", (str(other),))
    expected = {'title': 'Game', 'kind': 'game', 'path': str(other), 'root': ''}
    assert post({'id': 4, 'files': True, 'expected': expected}) == (200, {'ok': 1})
    assert other.exists()
    lost = root / 'after-db-error.mp4'; lost.write_text('x', encoding='utf8')
    app.sql("insert into items(id,title,kind,path,root,url) values(5,'DB error','video',?,'','db-error')", (str(lost),))
    expected = {'title': 'DB error', 'kind': 'video', 'path': str(lost), 'root': ''}
    real_sql = app.sql
    def fail_db(statement, args=()):
        if statement.startswith('delete from items where id='): raise app.sqlite3.DatabaseError('simulated')
        return real_sql(statement, args)
    with patch.object(app, 'sql', side_effect=fail_db):
        status, result = post({'id': 5, 'files': True, 'expected': expected})
    assert status == 500 and 'файлы уже могли' in result['error']
    assert not lost.exists() and app.sql('select id from items where id=5')
finally:
    server.shutdown(); server.server_close(); thread.join(); app.db.close()
'''
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run([sys.executable, '-c', code], env=dict(os.environ, MEDIAHUB_DATA_DIR=directory),
                           check=True, timeout=30)
