"""Folder layout selection and conservative scans on temporary data only."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from legacy import gamesweep
from storage import game_scan


class GameFolderScanTests(unittest.TestCase):
    def test_one_category_level_and_no_descent_into_game(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('College Traits v1.0', 'CollegeTraits v1.1'):
                folder = root / 'Категория' / name
                (folder / 'saves' / 'nested').mkdir(parents=True)
                (folder / 'saves' / 'nested' / 'slot.sav').write_bytes(b'save')
                (folder / 'game.exe').write_bytes(b'game')
            (root / 'Категория' / 'Other v1.0.zip').write_bytes(b'zip')
            (root / 'Incoming_Downloads').mkdir()
            games = gamesweep.scan_library(str(root), 'nested')
            self.assertEqual({g['name'] for g in games},
                             {'College Traits v1.0', 'CollegeTraits v1.1', 'Other v1.0.zip'})
            self.assertEqual(next(g['size'] for g in games if g['name'].endswith('v1.0')), 8)
            self.assertEqual(len(gamesweep.build_groups(games)), 1)
            tab = 'College Traits [v1.1] [Dev] – https://f95zone.to/threads/college-traits.12/'
            result = gamesweep.analyze_tabs(tab, games)['tabs'][0]
            self.assertEqual(result['verdict'], 'same')
            self.assertEqual(result['local']['count'], 2)
            self.assertEqual((root / 'Категория' / 'College Traits v1.0' / 'saves' / 'nested' / 'slot.sav').read_bytes(), b'save')

    def test_two_category_levels_and_flat_do_not_descend_past_chosen_depth(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            game = root / 'Категория' / 'Подпапка' / 'Game v1.0'
            (game / 'data' / 'saves').mkdir(parents=True)
            (game / 'data' / 'saves' / 'slot.sav').write_bytes(b'123')
            self.assertEqual([g['name'] for g in gamesweep.list_games(str(root), 'flat')], ['Категория'])
            self.assertEqual([g['name'] for g in gamesweep.list_games(str(root), 'nested')], ['Подпапка'])
            self.assertEqual([g['name'] for g in gamesweep.list_games(str(root), 'nested2')], ['Game v1.0'])
            self.assertTrue((game / 'data' / 'saves' / 'slot.sav').exists())
            with self.assertRaises(ValueError): gamesweep.list_games(str(root), 'invalid')

    def test_links_are_not_followed_and_failed_category_read_aborts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'root'; root.mkdir()
            outside = Path(directory) / 'outside'; outside.mkdir()
            (outside / 'Game v1.0').mkdir()
            try:
                (root / 'linked-category').symlink_to(outside, target_is_directory=True)
            except OSError:
                self.skipTest('creating directory links requires privileges')
            self.assertEqual(gamesweep.list_games(str(root), 'nested'), [])
            category = root / 'category'; category.mkdir()
            real_scandir = os.scandir
            def blocked(path):
                if os.path.normcase(os.fspath(path)) == os.path.normcase(str(category)):
                    raise PermissionError('test category unavailable')
                return real_scandir(path)
            with patch('storage.game_scan.os.scandir', side_effect=blocked):
                with self.assertRaises(PermissionError): game_scan.list_games(str(root), 'nested')

    def test_failed_scan_keeps_previous_results_and_does_not_sync(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'category').mkdir()
            store = gamesweep.Store(str(root))
            previous = [{'name': 'Existing', 'path': str(root / 'Existing'), 'type': 'folder', 'mtime': 0, 'size': 0}]
            store.games = previous[:]; store.scanned = True; store.running = True
            calls = []; store.on_done = lambda *_: calls.append(True)
            with patch('storage.game_scan.os.scandir', side_effect=PermissionError('no access')):
                store._scan(str(root), 'nested')
            self.assertEqual(store.games, previous)
            self.assertEqual(calls, [])
            self.assertIn('no access', store.error)
            self.assertFalse(store.running)

    @unittest.skipUnless(os.name == 'nt', 'Windows junctions')
    def test_windows_junctions_are_skipped_in_categories_and_game_stats(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'root'; root.mkdir()
            outside = Path(directory) / 'outside'; outside.mkdir()
            (outside / 'data.bin').write_bytes(b'outside')
            game = root / 'category' / 'Game v1.0'; game.mkdir(parents=True)
            (game / 'game.exe').write_bytes(b'game')
            links = [root / 'junction', game / 'junction']
            try:
                for link in links:
                    result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(outside)],
                                            capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                games = gamesweep.scan_library(str(root), 'nested')
                self.assertEqual([g['name'] for g in games], ['Game v1.0'])
                self.assertEqual(games[0]['size'], 4)
                self.assertEqual((outside / 'data.bin').read_bytes(), b'outside')
            finally:
                for link in links:
                    if link.exists(): os.rmdir(link)

    def test_http_setting_restart_scan_and_no_unseen_card_deletion(self):
        code = '''
import http.client, json, threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from legacy import app
root = app.BASE / 'games'; game = root / 'genre' / 'College Traits v1.0'
(game / 'saves').mkdir(parents=True); (game / 'saves' / 'slot.sav').write_bytes(b'keep')
app.cfg['folder'] = str(app.BASE / 'downloads')
app.cfg['games_root'] = str(root)
app.sql("insert into items(title,kind,path,url,info) values('existing','game',?,'game:existing','{}')", (str(game),))
server = ThreadingHTTPServer(('127.0.0.1',0), app.H)
thread = threading.Thread(target=server.serve_forever); thread.start()
def post(data):
    conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
    conn.request('POST','/api/settings',json.dumps(data),{'X-MH':'1'})
    response = conn.getresponse(); status = response.status; body = json.loads(response.read()); conn.close()
    return status, body
try:
    assert post({'games_layout':'invalid'})[0] == 400
    assert post({'games_layout':'nested'})[1]['games_layout'] == 'nested'
    assert json.loads(app.CFG.read_text(encoding='utf8'))['games_layout'] == 'nested'
    h = app.games_server(); original = h.store.on_done; finished = threading.Event()
    def done(games, path):
        try: original(games, path)
        finally: finished.set()
    h.store.on_done = done
    app.games_scan(str(root)); assert finished.wait(10)
    assert h.store.layout == 'nested'
    rows = app.sql("select title,path from items where kind='game'")
    assert any(r['title'] == 'College Traits' and r['path'] == str(game) for r in rows), [dict(r) for r in rows]
    assert any(r['title'] == 'existing' for r in rows), [dict(r) for r in rows]
    assert not any(r['title'] == 'saves' for r in rows)
    assert (game / 'saves' / 'slot.sav').read_bytes() == b'keep'
finally:
    server.shutdown(); server.server_close(); thread.join()
    if 'h' in app._gs: app._gs['h'].shutdown(); app._gs['h'].server_close()
    app.db.close()
'''
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run([sys.executable, '-c', code], check=True, timeout=30,
                           env=dict(os.environ, MEDIAHUB_DATA_DIR=directory))
