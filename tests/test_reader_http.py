"""Reader endpoints and progress against an isolated temporary manga library."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class ReaderHttpTests(unittest.TestCase):
    def test_reader_loads_chapter_and_saves_progress(self):
        code = r'''
import http.client, json, os, threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from legacy import app
root = Path(os.environ['MEDIAHUB_DATA_DIR']) / 'manga'
chapter = root / 'chapters' / '12'
chapter.mkdir(parents=True)
(chapter / '001.png').write_bytes(b'PNG test page')
manifest = {'slug':'example', 'title':'Тест', 'listed':[{'cid':'12', 'label':'Глава 1'}],
            'chapters':{'12':{'label':'Глава 1', 'files':['001.png'], 'expected':1, 'done':True}}}
(root / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False), encoding='utf8')
app.sql("insert into items(id,title,kind,path,root,url) values(1,'Тест','manga',?,?,?)",
        (str(chapter / '001.png'), str(root), 'manga:example'))
server = ThreadingHTTPServer(('127.0.0.1', 0), app.H)
thread = threading.Thread(target=server.serve_forever)
thread.start()
def request(method, path, body=None, headers=None):
    conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
    try:
        conn.request(method, path, body, headers or {})
        response = conn.getresponse()
        return response.status, response.read()
    finally:
        conn.close()
try:
    status, page = request('GET', '/m/1')
    assert status == 200 and b'/ui/reader.js' in page
    status, payload = request('GET', '/api/manga/1')
    data = json.loads(payload)
    assert status == 200 and data['chapters'][0]['files'] == ['001.png'] and data['progress'] is None
    assert request('GET', '/mi/1/12/001.png') == (200, b'PNG test page')
    body = json.dumps({'id':1, 'cid':'12', 'page':0})
    assert request('POST', '/api/progress', body)[0] == 403
    assert request('POST', '/api/progress', body, {'X-MH':'1'})[0] == 200
    status, payload = request('GET', '/api/manga/1')
    assert status == 200 and json.loads(payload)['progress'] == {'cid':'12', 'page':0}
    assert request('GET', '/api/manga/1', headers={'Host':'evil.example'})[0] == 403
finally:
    server.shutdown(); server.server_close(); thread.join(); app.db.close()
'''
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run([sys.executable, '-c', code], env=dict(os.environ, MEDIAHUB_DATA_DIR=directory),
                           check=True, timeout=30)
