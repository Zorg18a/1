"""Local-only candidate lookup and explicit linking through the real HTTP route."""
import os
import subprocess
import sys
import tempfile
import unittest


class LocalGameHttpTests(unittest.TestCase):
    def test_http_link_is_explicit_and_rejects_foreign_requests(self):
        code = r'''
import http.client, json, threading
from http.server import ThreadingHTTPServer
from legacy import app
root = app.BASE / 'PG'; folder = root / 'new7' / 'HiddenBadge_20260828c'
(folder / 'saves').mkdir(parents=True)
(folder / 'saves' / 'slot.sav').write_bytes(b'data')
extra = app.BASE / 'other'; other = extra / 'HiddenBadge_20260828c'; other.mkdir(parents=True)
(other / 'file.txt').write_text('keep', encoding='utf-8')
app.cfg['games_root'] = str(root)
app.sql("insert into items(id,title,kind,path,url,info) values(1,'Hidden Badge','game','','game:hiddenbadge','{}')")
server = ThreadingHTTPServer(('127.0.0.1', 0), app.H)
t = threading.Thread(target=server.serve_forever); t.start()
def post(data, headers=None):
    conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
    try:
        conn.request('POST','/api/game/incoming', json.dumps(data), headers or {})
        r = conn.getresponse(); content = r.read()
        return r.status, json.loads(content) if r.status != 403 else None
    finally: conn.close()
try:
    payload = {'id': 1, 'mode': 'local_search'}
    assert post(payload)[0] == 403
    assert post(payload, {'X-MH':'1','Origin':'https://evil.example'})[0] == 403
    extra_payload = {'id': 1, 'mode': 'local_search_other', 'root': str(extra)}
    assert post(extra_payload)[0] == 403
    assert post(extra_payload, {'X-MH':'1','Origin':'https://evil.example'})[0] == 403
    status, result = post(extra_payload, {'X-MH':'1'})
    assert status == 200 and result['root'] == str(extra), (status, result)
    found = next(c for c in result['candidates'] if c['path'] == str(other))
    assert 'token' not in found and found['association']['state'] == 'none'
    assert post({'id':1,'mode':'local_search_other','root':'relative'}, {'X-MH':'1'})[0] == 400
    assert app.sql('select path from items where id=1')[0]['path'] == ''
    assert (other / 'file.txt').read_text('utf-8') == 'keep'
    status, result = post(payload, {'X-MH':'1'})
    assert status == 200, (status, result)
    c = next(c for c in result['candidates'] if c['path'] == str(folder))
    assert app.sql('select path from items where id=1')[0]['path'] == ''
    assert post({'id': 1, 'mode': 'local_link', 'token':'fake'}, {'X-MH':'1'})[0] == 409
    assert post({'id': 1, 'mode': 'local_link', 'token':c['token']}, {'X-MH':'1'}) == (200, {'ok':1,'path':str(folder)})
    assert app.game_view(app.sql('select * from items where id=1')[0])['downloaded']
    for _ in range(2): app.sync_games(app.gamesweep.scan_library(str(root), 'auto'), str(root))
    rows = app.sql("select * from items where kind='game'")
    assert len(rows) == 1 and rows[0]['id'] == 1 and rows[0]['path'] == str(folder)
    assert (folder / 'saves' / 'slot.sav').read_bytes() == b'data'
finally:
    server.shutdown(); server.server_close(); t.join(); app.db.close()
'''
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run([sys.executable, '-c', code], env=dict(os.environ, MEDIAHUB_DATA_DIR=directory),
                           check=True, timeout=40)
