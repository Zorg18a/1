"""Integration test runs the server and scans only an isolated temporary library."""
import os
import subprocess
import sys
import tempfile
import unittest


class GameTagsHttpTests(unittest.TestCase):
    def test_tags_scan_and_http(self):
        code = r'''
import http.client, json, shutil, threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from legacy import app

root = Path(app.BASE) / 'games'
game = root / 'Sample Game'
(game / 'nested').mkdir(parents=True)
(game / 'nested' / 'data.bin').write_bytes(b'abcde')
app.cfg['games_root'] = str(root)
app.sync_games(app.gamesweep.scan_library(str(root)), str(root))
row = app.sql("select * from items where kind='game'")[0]
assert row['size'] == 5, row['size']
id = row['id']
server = ThreadingHTTPServer(('127.0.0.1', 0), app.H)
thread = threading.Thread(target=server.serve_forever)
thread.start()
def request(method, path, data=None, auth=True):
    c = http.client.HTTPConnection('127.0.0.1', server.server_port)
    headers = {'Content-Type': 'application/json'}
    if auth: headers['X-MH'] = '1'
    c.request(method, path, None if data is None else json.dumps(data), headers)
    r = c.getresponse(); status = r.status; body = r.read(); c.close()
    return status, json.loads(body) if r.getheader('Content-Type', '').startswith('application/json') else body
try:
    c = http.client.HTTPConnection('127.0.0.1', server.server_port)
    c.request('POST', '/api/game/tags', '{', {'X-MH': '1'})
    response = c.getresponse()
    assert response.status == 400 and 'error' in json.loads(response.read())
    c.close()
    assert request('POST', '/api/game/tags', {'id': id, 'tags': ['x']}, False)[0] == 403
    assert request('POST', '/api/game/tags', {'id': id, 'tags': ['  RPG ', 'rpg', 'Моё']}) == (200, {'tags': ['RPG', 'Моё']})
    assert request('POST', '/api/game/tags', {'id': id, 'tags': ['x' * 41]})[0] == 400
    assert request('POST', '/api/game/tags', {'id': 999999, 'tags': []})[0] == 404
    assert request('POST', '/api/game/set', {'id': id, 'note': 'note'})[0] == 200
    app.sync_games(app.gamesweep.scan_library(str(root)), str(root))
    status, items = request('GET', '/api/library')
    assert status == 200 and items[0]['g']['tags'] == ['RPG', 'Моё']
    assert items[0]['g']['note'] == 'note' and items[0]['size'] == 5
    assert request('POST', '/api/game/set', {'id': id, 'note': ''})[0] == 200
    shutil.rmtree(game)  # only the temporary test game, never user files
    app.sync_games(app.gamesweep.scan_library(str(root)), str(root))
    _, items = request('GET', '/api/library')
    assert items[0]['id'] == id and items[0]['g']['tags'] == ['RPG', 'Моё']
    assert not items[0]['g']['downloaded']
    assert request('POST', '/api/game/tags', {'id': id, 'tags': []}) == (200, {'tags': []})
finally:
    server.shutdown(); server.server_close(); thread.join(); app.db.close()
'''
        with tempfile.TemporaryDirectory() as directory:
            env = dict(os.environ, MEDIAHUB_DATA_DIR=directory)
            subprocess.run([sys.executable, '-c', code], env=env, check=True, timeout=30)
