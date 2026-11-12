"""External-root links and save previews through the real local HTTP API."""
import os
import subprocess
import sys
import tempfile
import unittest


class ExtraGameLinkHttpTests(unittest.TestCase):
    def test_link_save_preview_and_later_scans(self):
        code = r'''
import http.client, json, threading, zipfile
from core.local_http import LocalHTTPServer
from legacy import app
base = app.BASE; main = base / 'main'; main.mkdir()
extra = base / 'other'; folder = extra / 'category' / 'HiddenBadge_20260828c'
(folder / 'saves').mkdir(parents=True); (folder / 'saves' / 'slot.sav').write_bytes(b'keep')
downloads = base / 'downloads'; downloads.mkdir()
app.cfg.update(games_root=str(main), folder=str(downloads))
app.sql("insert into items(id,title,kind,path,url,info) values(1,'Hidden Badge','game','','game:hiddenbadge',?)", (json.dumps({'note':'keep'}),))
server = LocalHTTPServer(('127.0.0.1', 0), app.H)
t = threading.Thread(target=server.serve_forever); t.start()
def post(path, data, headers=None):
    c = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
    try:
        c.request('POST', path, json.dumps(data), headers or {'X-MH':'1'})
        r = c.getresponse(); body = r.read()
        return r.status, json.loads(body) if r.status != 403 else None
    finally: c.close()
try:
    search = {'id':1, 'mode':'local_search_other', 'root':str(extra)}
    assert post('/api/game/incoming', search, {'X-MH':'1','Origin':'https://evil.example'})[0] == 403
    status, data = post('/api/game/incoming', search); assert status == 200, (status,data)
    candidate = next(c for c in data['candidates'] if c['path'] == str(folder))
    assert app.sql('select path from items where id=1')[0]['path'] == ''
    status, result = post('/api/game/incoming', {'id':1,'mode':'local_link','token':candidate['token']})
    assert status == 200 and result['path'] == str(folder), (status,result)
    assert app.cfg['games_root'] == str(main) and app.game_view(app.sql('select * from items where id=1')[0])['downloaded']
    for mode, key in (('saves','save_preview'), ('save_inventory','save_inventory')):
        status, result = post('/api/game/incoming', {'id':1,'mode':mode})
        assert status == 200 and result[key]['game_folder'] == str(folder), (status,result)
    app.cfg['games_root'] = str(base / 'another-root')
    status, result = post('/api/game/incoming', {'id':1,'mode':'saves'})
    assert status == 200 and result['save_preview']['game_folder'] == str(folder), (status,result)
    app.cfg['games_root'] = str(main)
    status, data = post('/api/game/incoming', {'id':1}); incoming = __import__('pathlib').Path(data['folder'])
    archive = incoming / 'Hidden Badge v2.zip'
    with zipfile.ZipFile(archive, 'w') as z: z.writestr('saves/new.sav', b'new')
    data = post('/api/game/incoming', {'id':1})[1]; candidate = data['candidates'][0]
    status, data = post('/api/game/zip-inspect', {'id':1,'name':candidate['name'], 'identity':candidate['identity'],'compare_saves':True})
    assert status == 200 and data['inspection']['save_comparison']['game_folder'] == str(folder), (status,data)
    app.sync_games(app.gamesweep.scan_library(str(extra), 'nested'), str(extra))
    row = app.sql('select * from items where id=1')[0]; info = json.loads(row['info'])
    assert row['path'] == str(folder) and info['mediahub_extra_game_root_v1'] == str(extra) and info['note'] == 'keep'
    (main / 'Hidden Badge').mkdir()
    store = app.gamesweep.Store(str(main)); store.running = True; store.on_done = app.sync_games
    store._scan(str(main), 'flat')
    assert 'вручную выбранной связи' in store.error, store.error
    assert app.sql('select path from items where id=1')[0]['path'] == str(folder)
    assert (folder / 'saves' / 'slot.sav').read_bytes() == b'keep'
finally:
    server.shutdown(); server.server_close(); t.join(); app.db.close()
'''
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, '-c', code], env=dict(os.environ, MEDIAHUB_DATA_DIR=directory),
                                    text=True, capture_output=True, timeout=40)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
