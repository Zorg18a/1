"""Test authenticated, non-destructive archive discovery using temporary data only."""
import os
import subprocess
import sys
import tempfile
import unittest


class IncomingHttpTests(unittest.TestCase):
    def test_preview_http_without_installation(self):
        code = r'''
import http.client, json, threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from legacy import app
base = Path(app.BASE)
downloads, games = base / 'MediaHub', base / 'Games'
downloads.mkdir(); games.mkdir()
game = games / 'Example Game v1.0'
game.mkdir(); (game / 'save.sav').write_bytes(b'old save')
app.cfg['folder'] = str(downloads); app.cfg['games_root'] = str(games)
app.sync_games(app.gamesweep.scan_library(str(games)), str(games))
r = app.sql("select * from items where kind='game'")[0]; item_id = r['id']
reserved = games / 'Incoming_Downloads'; reserved.mkdir()
(reserved / 'old.zip').write_bytes(b'preserve')
app.sql("insert into items(title,kind,path,url,src,info) values(?,?,?,?,?,?)", ('Old card', 'game', str(reserved / 'old.zip'), 'game:old-card', str(games), json.dumps({'inst': {'root': str(games)}})))
app.sync_games(app.gamesweep.scan_library(str(games)), str(games))
assert app.sql("select id from items where url='game:old-card'")
assert (reserved / 'old.zip').read_bytes() == b'preserve'
server = ThreadingHTTPServer(('127.0.0.1', 0), app.H)
thread = threading.Thread(target=server.serve_forever); thread.start()
def request(data, auth=True):
    c = http.client.HTTPConnection('127.0.0.1', server.server_port)
    headers = {'Content-Type': 'application/json'}
    if auth: headers['X-MH'] = '1'
    c.request('POST', '/api/game/incoming', json.dumps(data), headers)
    response = c.getresponse(); status = response.status; body = response.read(); c.close()
    return status, json.loads(body) if response.getheader('Content-Type', '').startswith('application/json') else body
try:
    incoming = downloads / 'Incoming_Downloads'
    assert request({'id': item_id}, False)[0] == 403 and not incoming.exists()
    assert request({'id': True})[0] == 400 and not incoming.exists()
    assert request({'id': 99999})[0] == 404 and not incoming.exists()
    assert request({'id': item_id, 'mode': 'saves'}, False)[0] == 403
    assert request({'id': item_id, 'mode': 'saves', 'path': str(base)})[0] == 400
    status, result = request({'id': item_id, 'mode': 'saves'})
    assert status == 200 and result['save_preview']['candidates'] == [{'path': 'save.sav', 'kind': 'file'}], (status, result)
    assert not incoming.exists() and (game / 'save.sav').read_bytes() == b'old save'
    (game / 'saves' / 'nested').mkdir(parents=True)
    (game / 'saves' / 'nested' / 'slot.bin').write_bytes(b'fixture')
    assert request({'id': item_id, 'mode': 'save_inventory'}, False)[0] == 403
    assert request({'id': item_id, 'mode': 'save_inventory', 'path': str(base)})[0] == 400
    status, result = request({'id': item_id, 'mode': 'save_inventory'})
    assert status == 200, (status, result)
    files = {f['path'].replace('\\', '/'): f['size_bytes'] for f in result['save_inventory']['files']}
    assert files == {'save.sav': '8', 'saves/nested/slot.bin': '7'}, files
    assert result['save_inventory']['total_bytes'] == '15' and not result['save_inventory']['incomplete']
    assert not incoming.exists() and (game / 'saves' / 'nested' / 'slot.bin').read_bytes() == b'fixture'
    status, result = request({'id': item_id})
    assert status == 200 and incoming.is_dir() and not result['candidates']
    assert result['installed_path'] == str(game) and result['installed_version'] == '1.0'
    good = incoming / 'Example Game v1.2.zip'; good.write_bytes(b'archive fixture')
    other = incoming / 'Example Game 2 v1.2.zip'; other.write_bytes(b'other archive')
    status, result = request({'id': item_id, 'path': str(other)})
    assert status == 200 and [x['name'] for x in result['candidates']] == [good.name]
    assert result['candidates'][0]['version'] == '1.2'
    assert good.read_bytes() == b'archive fixture' and other.read_bytes() == b'other archive'
    assert (game / 'save.sav').read_bytes() == b'old save'
    assert app.sql('select path from items where id=?', (item_id,))[0]['path'] == str(game)
    app.cfg['games_root'] = str(downloads)
    assert request({'id': item_id, 'mode': 'saves'})[0] == 400
    assert request({'id': item_id})[0] == 400
    assert good.read_bytes() == b'archive fixture'
finally:
    server.shutdown(); server.server_close(); thread.join(); app.db.close()
'''
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run([sys.executable, '-c', code], env=dict(os.environ, MEDIAHUB_DATA_DIR=directory),
                           check=True, timeout=30)
