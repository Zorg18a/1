"""Comparison must use the server-selected archive and game without modifying files."""
import os
import subprocess
import sys
import tempfile
import unittest


class SaveCompareHttpTests(unittest.TestCase):
    def test_read_only_comparison(self):
        code = r'''
import http.client, json, threading, zipfile
from pathlib import Path
from http.server import ThreadingHTTPServer
from legacy import app
base = Path(app.BASE).resolve(); downloads = base / 'downloads'; downloads.mkdir()
games = base / 'games'; games.mkdir(); game = games / 'Example Game v1'; game.mkdir()
(game / 'saves').mkdir(); (game / 'saves' / 'real.sav').write_bytes(b'keep')
(game / 'slot.sav').write_bytes(b'old')
app.cfg['folder'] = str(downloads); app.cfg['games_root'] = str(games)
app.sync_games(app.gamesweep.scan_library(str(games)), str(games))
id = app.sql("select id from items where kind='game'")[0]['id']
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
    _, initial = post('/api/game/incoming', {'id': id})
    folder = Path(initial['folder']); archive = folder / 'Example Game v2.zip'
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr('saves/new.sav', 'new'); z.writestr('SLOT.SAV', 'new slot')
    before = archive.read_bytes()
    _, initial = post('/api/game/incoming', {'id': id}); candidate = initial['candidates'][0]
    payload = {'id': id, 'name': candidate['name'], 'identity': candidate['identity'], 'compare_saves': True}
    assert post('/api/game/zip-inspect', payload, False)[0] == 403
    assert post('/api/game/zip-inspect', dict(payload, path=str(base)))[0] == 400
    assert post('/api/game/zip-inspect', dict(payload, verify_data=True))[0] == 400
    assert post('/api/game/zip-inspect', dict(payload, compare_saves='yes'))[0] == 400
    status, result = post('/api/game/zip-inspect', payload)
    assert status == 200, (status, result)
    summary = result['inspection']; assert '_entries' not in summary
    comparison = summary['save_comparison']
    assert comparison['incomplete'] is False and Path(comparison['game_folder']) == game
    got = {x['path']: x['relation'] for x in comparison['candidates']}
    assert got == {'saves': 'directory_shared', 'slot.sav': 'file_same_path'}, got
    assert archive.read_bytes() == before and (game / 'saves' / 'real.sav').read_bytes() == b'keep'
    assert (game / 'slot.sav').read_bytes() == b'old'
    assert sorted(p.name for p in folder.iterdir()) == [archive.name]
    assert post('/api/game/zip-inspect', dict(payload, identity='a'*64))[0] == 409
    unsafe = folder / 'Example Game v3.zip'
    with zipfile.ZipFile(unsafe, 'w') as z: z.writestr('../escape.sav', 'unsafe')
    _, updated = post('/api/game/incoming', {'id': id})
    rejected = next(c for c in updated['candidates'] if c['name'] == unsafe.name)
    assert post('/api/game/zip-inspect', {'id': id, 'name': rejected['name'], 'identity': rejected['identity'], 'compare_saves': True})[0] == 422
    assert not (base / 'escape.sav').exists() and archive.read_bytes() == before
    app.cfg['games_root'] = str(downloads)
    assert post('/api/game/zip-inspect', payload)[0] == 400
finally:
    server.shutdown(); server.server_close(); thread.join(); app.db.close()
'''
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, '-c', code], env=dict(os.environ, MEDIAHUB_DATA_DIR=directory),
                                    text=True, capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
