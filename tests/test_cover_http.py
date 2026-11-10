"""End-to-end scan, storage and HTTP on disposable game/data folders."""
import os
import subprocess
import sys
import tempfile
import unittest


class CoverHttpTests(unittest.TestCase):
    def test_game_cover_cache_and_legacy_paths(self):
        code = r'''
import base64, http.client, json, threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from legacy import app

png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/aN8AAAAASUVORK5CYII=')
base = Path(app.BASE)
root, downloads = base / 'games', base / 'MediaHub'
game = root / 'Alpha Game'
game.mkdir(parents=True)
(game / 'cover.png').write_bytes(png)
(game / 'game.dat').write_bytes(b'game contents')
archive = root / 'Archived Game.zip'
archive.write_bytes(b'not opened or changed')
app.cfg['folder'] = str(downloads)
def scan():
    app.sync_games(app.gamesweep.scan_library(str(root)), str(root))
scan()
rows = app.sql("select * from items where kind='game' order by title")
assert len(rows) == 2
row = next(r for r in rows if r['path'] == str(game))
old_id = row['id']
cached = Path(row['thumb'])
assert cached.parent == downloads / 'covers' and cached.read_bytes() == png
assert row['size'] == len(png) + len(b'game contents')
assert archive.read_bytes() == b'not opened or changed'
server = ThreadingHTTPServer(('127.0.0.1', 0), app.H)
thread = threading.Thread(target=server.serve_forever); thread.start()
def get(path):
    c = http.client.HTTPConnection('127.0.0.1', server.server_port)
    c.request('GET', path); r = c.getresponse(); status, body = r.status, r.read(); c.close()
    return status, body
try:
    assert get(f'/t/{old_id}') == (200, png)
    scan()
    assert app.sql('select thumb from items where id=?', (old_id,))[0]['thumb'] == str(cached)
    # Existing legacy cached covers remain authoritative and are not moved.
    legacy = base / 'old' / 'Games' / 'covers' / 'legacy.png'
    legacy.parent.mkdir(parents=True); legacy.write_bytes(png)
    app.sql('update items set thumb=? where id=?', (str(legacy), old_id))
    scan()
    assert app.sql('select thumb from items where id=?', (old_id,))[0]['thumb'] == str(legacy)
    assert get(f'/t/{old_id}') == (200, png) and cached.exists()
    legacy.unlink()  # disposable test fixture only
    _, body = get('/api/library')
    item = next(x for x in json.loads(body) if x['id'] == old_id)
    assert item['cover'] == ''
    scan()
    replacement = Path(app.sql('select thumb from items where id=?', (old_id,))[0]['thumb'])
    assert replacement.parent == downloads / 'covers' and replacement.read_bytes() == png
    assert (game / 'cover.png').read_bytes() == png
    assert (game / 'game.dat').read_bytes() == b'game contents'
    assert archive.read_bytes() == b'not opened or changed'
    # If downloads and game root coincide, the app cache is not imported as a game.
    app.cfg['folder'] = str(root)
    app.sql("update items set thumb='' where id=?", (old_id,))
    scan(); scan()
    assert (root / 'covers').is_dir()
    assert len(app.sql("select id from items where kind='game'")) == 2
    with patch.object(app.cover_download, 'download_cover', return_value=png) as download:
        nid = app.apply_meta({'name': 'Network Game', 'cover': 'https://example.test/image.png', 'version': '1'}, 'https://example.test/thread')
    network_cover = Path(app.sql('select thumb from items where id=?', (nid,))[0]['thumb'])
    assert download.call_count == 1 and network_cover.parent == root / 'covers' and network_cover.read_bytes() == png
    with patch.object(app.cover_download, 'download_cover', side_effect=OSError('offline')):
        failed_id = app.apply_meta({'name': 'Offline Game', 'cover': 'https://example.test/image.png', 'version': '1'}, 'https://example.test/thread')
    assert not app.sql('select thumb from items where id=?', (failed_id,))[0]['thumb']
finally:
    server.shutdown(); server.server_close(); thread.join(); app.db.close()
'''
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run([sys.executable, '-c', code], env=dict(os.environ, MEDIAHUB_DATA_DIR=directory),
                           check=True, timeout=30)
