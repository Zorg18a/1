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
other = root.parent / 'other'
(other / 'chapters' / '12').mkdir(parents=True)
(other / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False), encoding='utf8')
(other / 'chapters' / '12' / '001.png').write_bytes(b'Other manga page')
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
    assert data['progress_save_allowed'] is True and data['progress_slug'] == 'example'
    assert request('GET', '/mi/1/12/001.png') == (200, b'PNG test page')
    assert request('GET', '/mi/1/12/001.png?retry=1-1') == (200, b'PNG test page')
    image_id = data['image_identity']; assert len(image_id) == 64
    status, recent_data = request('GET', '/api/recent/1')
    recent = json.loads(recent_data)
    assert status == 200 and recent['live_identity'] == image_id and str(root).encode() not in recent_data
    assert request('GET', '/ui/recent.js')[0] == 200
    assert request('GET', '/api/recent/1', headers={'Host':'evil.example'})[0] == 403
    image_path = '/mi/1/12/001.png?identity=' + image_id
    assert request('GET', image_path) == (200, b'PNG test page')
    assert request('GET', image_path, headers={'Host':'evil.example'})[0] == 403
    assert request('GET', image_path + '&retry=1-1') == (200, b'PNG test page')
    assert request('GET', image_path, headers={'Range':'bytes=0-2'}) == (206, b'PNG')
    for query in ('identity=', 'identity=bad', 'identity=' + image_id + '&identity=' + image_id):
        status, payload = request('GET', '/mi/1/12/001.png?' + query)
        assert status == 400 and json.loads(payload)['error']
    app.sql('update items set root=? where id=1', (str(other),))
    changed = json.loads(request('GET', '/api/recent/1')[1])
    assert changed['identity'] != recent['identity'] and changed['live_identity'] != image_id
    status, payload = request('GET', image_path)
    assert status == 409 and json.loads(payload)['error']
    assert request('GET', '/mi/1/12/001.png') == (200, b'Other manga page')
    status, payload = request('GET', '/api/manga/1')
    assert status == 200 and json.loads(payload)['image_identity'] != image_id
    app.sql('update items set root=? where id=1', (str(root),))
    body = json.dumps({'id':1, 'cid':'12', 'page':0})
    assert request('POST', '/api/progress', body)[0] == 403
    assert request('POST', '/api/progress', body, {'X-MH':'1'})[0] == 200
    assert request('POST', '/api/progress', json.dumps({'id':'1', 'cid':'12', 'page':'0'}), {'X-MH':'1'})[0] == 200
    app.sql("insert into items(id,title,kind,url) values(2,'Video','video','video:example')")
    app.sql("insert into items(id,title,kind,url) values(3,'Wrong','manga','not-manga:example')")
    for bad_id in (2, 3, 999):
        status, payload = request('POST', '/api/progress', json.dumps({'id':bad_id, 'cid':'12', 'page':0}), {'X-MH':'1'})
        assert status == 404 and json.loads(payload)['error']
    for data in ({'id': True, 'cid':'12', 'page':0}, {'id':1, 'cid':'', 'page':0},
                 {'id':1, 'cid':'12', 'page':-1}, {'id':1, 'cid':'12', 'page':1.5}, {}):
        status, payload = request('POST', '/api/progress', json.dumps(data), {'X-MH':'1'})
        assert status == 400 and json.loads(payload)['error'], (status, data, payload)
    status, payload = request('GET', '/api/manga/1')
    assert status == 200 and json.loads(payload)['progress'] == {'cid':'12', 'page':0}
    token = json.loads(payload)['progress_snapshot']
    identity = json.loads(payload)['progress_identity']
    assert len(token) == len(identity) == 64 and str(root).encode() not in payload
    conditional = {'id': 1, 'cid': '13', 'page': 2, 'slug': 'example', 'snapshot': token, 'identity': identity}
    status, payload = request('POST', '/api/progress', json.dumps(conditional), {'X-MH':'1'})
    assert status == 200 and json.loads(payload)['snapshot'] != token
    newer = json.loads(payload)['snapshot']
    app.sql('update items set root=? where id=1', (str(root / 'different'),))
    status, payload = request('POST', '/api/progress', json.dumps({**conditional, 'snapshot': newer, 'page': 9}), {'X-MH':'1'})
    assert status == 409 and json.loads(payload)['error']
    assert tuple(app.sql("select cid,page from progress where slug='example'")[0]) == ('13', 2)
    app.sql('update items set root=? where id=1', (str(root),))
    status, payload = request('POST', '/api/progress', json.dumps({**conditional, 'page': 3}), {'X-MH':'1'})
    assert status == 409 and json.loads(payload)['error']
    status, payload = request('GET', '/api/manga/1')
    assert json.loads(payload)['progress'] == {'cid':'13', 'page':2}
    guarded = json.dumps({'id': 1, 'cid': '12', 'page': 1, 'slug': 'example'})
    assert request('POST', '/api/progress', guarded, {'X-MH':'1'})[0] == 200
    app.sql("update items set url='manga:other' where id=1")
    status, payload = request('POST', '/api/progress', guarded, {'X-MH':'1'})
    assert status == 409 and json.loads(payload)['error']
    status, payload = request('GET', '/api/manga/1')
    mismatch = json.loads(payload)
    assert status == 200 and mismatch['progress_save_allowed'] is False and mismatch['progress_slug'] is None
    assert mismatch['progress'] == {'cid':'12', 'page':1}
    assert request('GET', image_path)[0] == 409
    assert request('GET', '/mi/1/12/001.png?identity=' + mismatch['image_identity']) == (200, b'PNG test page')
    assert not app.sql("select * from progress where slug='other'")
    assert request('GET', '/api/manga/1', headers={'Host':'evil.example'})[0] == 403
finally:
    server.shutdown(); server.server_close(); thread.join(); app.db.close()
'''
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run([sys.executable, '-c', code], env=dict(os.environ, MEDIAHUB_DATA_DIR=directory),
                           check=True, timeout=30)
