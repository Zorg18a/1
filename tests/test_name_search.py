"""Joined/spaced names: display search and conservative game matching on temporary data."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

from core.search import contains
from core.update_inspect import inspect_request
from core.update_preview import preview_request
from legacy import gamesweep
from storage.incoming_downloads import incoming_folder


class NameSearchTests(unittest.TestCase):
    def test_display_search(self):
        for value, query in [('College Traits', 'CollegeTraits'), ('CollegeTraits', 'College Traits'),
                             ('college-traits', 'COLLEGE_TRAITS'), ('Школа Игр', 'школаигр'),
                             ('College Traits 2', 'CollegeTraits 2')]:
            self.assertTrue(contains(value, query), (value, query))
        self.assertFalse(contains('CollegeTraits', 'College Traits 2'))
        self.assertFalse(contains('abc', '---'))
        self.assertTrue(contains('abc---def', '---'))
        self.assertFalse(contains(None, 'CollegeTraits'))

    def test_versions_and_tabs_with_joined_and_spaced_names(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('CollegeTraits v1.0', 'College Traits v1.1', 'College Traits 2 v1.0'):
                (root / name).mkdir()
            games = gamesweep.scan_library(directory)
            groups = gamesweep.build_groups(games)
            self.assertEqual(len(groups), 1)
            self.assertEqual({m['name'] for m in groups[0]['members']},
                             {'CollegeTraits v1.0', 'College Traits v1.1'})
            self.assertEqual({m['status'] for m in groups[0]['members']}, {'старая', 'оставить'})
            text = ('College Traits [v1.1] [Dev] – https://f95zone.to/threads/college-traits.12/\n'
                    'CollegeTraits [v1.2] [Dev] – https://f95zone.to/threads/collegetraits.13/\n'
                    'https://f95zone.to/threads/college-traits-v1-1-dev.14/')
            result = gamesweep.analyze_tabs(text, games)['tabs']
            self.assertEqual([r['verdict'] for r in result], ['same', 'update', 'same'])
            for row in result:
                self.assertEqual(row['local']['count'], 2)
                self.assertEqual(row['local']['name'], 'College Traits v1.1')
                self.assertTrue(row['sure'])
            self.assertNotEqual(gamesweep.parse_name('College Traits 2 v1.0')['key'],
                                gamesweep.parse_name('CollegeTraits v1.0')['key'])

    def test_game_cards_and_disk_scan_do_not_merge_numbered_sequels(self):
        code = '''
import json
from pathlib import Path
from legacy import app
root = app.BASE / 'games'; root.mkdir()
app.cfg['folder'] = str(app.BASE / 'downloads')
first = root / 'College Traits v1.0'; first.mkdir()
second = root / 'CollegeTraits 2 v1.0'; second.mkdir()
id1 = app.apply_meta({'name': 'CollegeTraits', 'version': '1.1'}, 'https://example.org/1')
id2 = app.apply_meta({'name': 'College Traits 2', 'version': '1.1'}, 'https://example.org/2')
assert id1 != id2
app.sync_games(app.gamesweep.scan_library(str(root)), str(root))
a, b = app.sql('select * from items where id=?', (id1,))[0], app.sql('select * from items where id=?', (id2,))[0]
assert a['path'] == str(first) and b['path'] == str(second), (dict(a), dict(b))
assert json.loads(a['info'])['meta']['thread'].endswith('/1')
assert json.loads(b['info'])['meta']['thread'].endswith('/2')
assert first.is_dir() and second.is_dir()
app.db.close()
'''
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run([sys.executable, '-c', code], check=True, timeout=30,
                           env=dict(os.environ, MEDIAHUB_DATA_DIR=directory))

    def test_update_archive_suggestions_stay_exact_and_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = incoming_folder(directory)
            names = ('College Traits v1.2.zip', 'CollegeTraits v1.3.zip', 'College Traits 2 v1.2.zip')
            for name in names: (folder / name).write_bytes(b'unchanged')
            view = lambda _: {'path': '', 'version': '', 'latest': ''}
            for title in ('CollegeTraits', 'College Traits'):
                result, status = preview_request({'id': 1}, lambda _: {'title': title}, view,
                                                 gamesweep.parse_name, directory, '')
                self.assertEqual(status, 200)
                self.assertEqual({r['name'] for r in result['candidates']}, set(names[:2]))
            self.assertTrue(all((folder / name).read_bytes() == b'unchanged' for name in names))

    def test_spaced_archive_can_be_inspected_for_joined_title(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = incoming_folder(directory)
            archive = folder / 'College Traits v1.2.zip'
            with zipfile.ZipFile(archive, 'w') as z:
                z.writestr('game/readme.txt', 'fixture')
            before = archive.read_bytes()
            game = {'title': 'CollegeTraits', 'path': ''}
            lookup = lambda _: game
            view = lambda _: {'path': '', 'version': '', 'latest': ''}
            result, status = preview_request({'id': 1}, lookup, view, gamesweep.parse_name, directory, '')
            self.assertEqual(status, 200)
            candidate = result['candidates'][0]
            inspection, status = inspect_request({'id': 1, 'name': candidate['name'], 'identity': candidate['identity']},
                                                 lookup, gamesweep.parse_name, directory, '')
            self.assertEqual(status, 200)
            self.assertEqual(inspection['inspection']['files'], 1)
            self.assertEqual(archive.read_bytes(), before)

    def test_library_http_search_both_directions_and_fields(self):
        code = '''
import http.client, json, threading
from urllib.parse import quote
from http.server import ThreadingHTTPServer
from legacy import app
for i, (title, author, topic, kind) in enumerate([
    ('College Traits', '', '', 'video'), ('CollegeTraits', '', '', 'audio'),
    ('Other', 'College Traits', '', 'video'), ('Other2', '', 'CollegeTraits', 'video'),
    ('Unrelated', '', '', 'video')], 1):
    app.sql('insert into items(id,title,author,topic,kind,path,url) values(?,?,?,?,?,?,?)',
            (i,title,author,topic,kind,'','item:'+str(i)))
server = ThreadingHTTPServer(('127.0.0.1', 0), app.H)
thread = threading.Thread(target=server.serve_forever); thread.start()
def get(query):
    conn = http.client.HTTPConnection('127.0.0.1', server.server_port)
    conn.request('GET', '/api/library?q='+quote(query))
    response = conn.getresponse(); data = json.loads(response.read()); conn.close()
    assert response.status == 200, data
    return {x['id'] for x in data}
try:
    assert get('CollegeTraits') == {1,2,3,4}
    assert get('College Traits') == {1,2,3,4}
    assert get('College Traits 2') == set()
    assert get('%%') == {1,2,3,4,5}  # legacy LIKE wildcards still work
finally:
    server.shutdown(); server.server_close(); thread.join(); app.db.close()
'''
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run([sys.executable, '-c', code], check=True, timeout=30,
                           env=dict(os.environ, MEDIAHUB_DATA_DIR=directory))
