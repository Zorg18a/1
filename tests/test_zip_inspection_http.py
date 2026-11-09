"""HTTP ZIP metadata inspection in temporary folders only."""
import os
import subprocess
import sys
import tempfile
import unittest


class ZipInspectionHttpTests(unittest.TestCase):
    def test_authenticated_zip_inspection(self):
        code = r'''
import http.client, json, threading, zipfile
from http.server import ThreadingHTTPServer
from pathlib import Path
from legacy import app
base = Path(app.BASE); downloads = base / 'downloads'; downloads.mkdir()
app.cfg['folder'] = str(downloads)
app.sql("insert into items(title,kind,url,path,info) values(?,?,?,?,?)", ('Example Game', 'game', 'game:examplegame', '', '{}'))
id = app.sql("select id from items where url='game:examplegame'")[0]['id']
server = ThreadingHTTPServer(('127.0.0.1', 0), app.H)
thread = threading.Thread(target=server.serve_forever); thread.start()
def post(path, body, auth=True):
    c = http.client.HTTPConnection('127.0.0.1', server.server_port)
    headers = {'Content-Type': 'application/json'}
    if auth: headers['X-MH'] = '1'
    c.request('POST', path, json.dumps(body), headers); r = c.getresponse()
    status, content = r.status, r.read(); c.close()
    return status, json.loads(content) if r.getheader('Content-Type', '').startswith('application/json') else content
try:
    assert post('/api/game/zip-inspect', {'id': id}, False)[0] == 403
    status, initial = post('/api/game/incoming', {'id': id}); assert status == 200
    folder = Path(initial['folder']); archive = folder / 'Example Game v2.0.zip'
    with zipfile.ZipFile(archive, 'w') as z: z.writestr('game/file.txt', 'fixture')
    other = folder / 'Other Game.zip'
    with zipfile.ZipFile(other, 'w') as z: z.writestr('other.txt', 'other')
    original = archive.read_bytes(); other_before = other.read_bytes()
    _, initial = post('/api/game/incoming', {'id': id}); candidate = initial['candidates'][0]
    payload = {'id': id, 'name': candidate['name'], 'identity': candidate['identity']}
    assert post('/api/game/zip-inspect', {'id': id, 'name': '../other.zip', 'identity': 'a' * 64})[0] == 400
    assert post('/api/game/zip-inspect', {'id': id, 'name': 'Other Game.zip', 'identity': 'a' * 64})[0] == 400
    assert post('/api/game/zip-inspect', {'id': id, 'name': candidate['name'], 'identity': 'a' * 64})[0] == 409
    status, result = post('/api/game/zip-inspect', payload)
    assert status == 200 and result['inspection']['files'] == 1
    assert archive.read_bytes() == original and other.read_bytes() == other_before
    assert sorted(p.name for p in folder.iterdir()) == sorted([archive.name, other.name])
    unsafe = folder / 'Example Game v3.0.zip'
    with zipfile.ZipFile(unsafe, 'w') as z: z.writestr('../outside', 'not extracted')
    _, updated = post('/api/game/incoming', {'id': id})
    rejected = next(c for c in updated['candidates'] if c['name'] == unsafe.name)
    assert post('/api/game/zip-inspect', {'id': id, 'name': unsafe.name, 'identity': rejected['identity']})[0] == 422
    assert not (folder.parent / 'outside').exists()
    assert archive.read_bytes() == original and other.read_bytes() == other_before
    with archive.open('ab') as output: output.write(b'x')
    assert post('/api/game/zip-inspect', payload)[0] == 409
    assert other.read_bytes() == other_before
    assert post('/api/game/zip-inspect', {'id': 99999, 'name': archive.name, 'identity': 'a' * 64})[0] == 404
finally:
    server.shutdown(); server.server_close(); thread.join(); app.db.close()
'''
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run([sys.executable, '-c', code], env=dict(os.environ, MEDIAHUB_DATA_DIR=directory),
                           check=True, timeout=30)
