"""Explicit association of a suggested folder, only on throwaway databases."""
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch
import unittest

from core import local_game_match
from legacy import gamesweep
from storage import game_associations, local_game_search
from storage.database import open_database


class LocalGameMatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / 'PG'
        self.folder = self.root / 'new7' / 'HiddenBadge_20260828c'
        (self.folder / 'saves').mkdir(parents=True)
        (self.folder / 'saves' / 'save.sav').write_bytes(b'preserve')
        self.db, self.lock = open_database(Path(self.temp.name) / 'library.db')
        self.db.execute('alter table items add column info')
        self.info = {'meta': {'thread': 'https://example.com/', 'version': '1'}, 'note': 'keep'}
        self.db.execute("insert into items(id,title,kind,path,url,info) values(1,'Hidden Badge','game','','game:hiddenbadge',?)",
                        (json.dumps(self.info),))
        self.db.commit()
        self.cfg = {'games_root': str(self.root)}

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def row(self):
        return self.db.execute('select * from items where id=1').fetchone()

    def find(self):
        data, status = local_game_match.find(self.row(), str(self.root), gamesweep.parse_name, self.db, self.lock)
        self.assertEqual(status, 200, data)
        return data

    def link(self, token, item_id=1):
        return local_game_match.link({'id': item_id, 'token': token}, self.db, self.lock, self.cfg)

    def test_date_suffix_is_suggestion_not_global_version_or_deletion_rule(self):
        parsed = gamesweep.parse_name(self.folder.name)
        self.assertEqual(parsed['key'], 'hiddenbadge20260828c')
        self.assertIsNone(parsed['nums'])
        self.assertTrue(local_game_search.candidate_match(self.folder.name, 'Hidden Badge', gamesweep.parse_name))
        for name, title in [('HiddenBadge2_20260828c', 'Hidden Badge'), ('HiddenBadge_20261399c', 'Hidden Badge'),
                            ('HiddenBadge_20260828c', 'Hidden Badge 2'), ('Go_20260828', 'Go')]:
            self.assertIsNone(local_game_search.candidate_match(name, title, gamesweep.parse_name))
        self.assertEqual(self.row()['path'], '')

    def test_explicit_association_preserves_card_and_files(self):
        results = self.find()
        candidate = next(c for c in results['candidates'] if c['path'] == str(self.folder))
        self.assertEqual(candidate['kind'], 'folder')
        self.assertEqual(self.row()['path'], '')
        response, status = self.link(candidate['token'])
        self.assertEqual(status, 200, response)
        self.assertEqual(self.row()['path'], str(self.folder))
        info = json.loads(self.row()['info'])
        self.assertEqual(info['meta'], self.info['meta']); self.assertEqual(info['note'], 'keep')
        self.assertEqual(info['inst']['version'], '')
        self.assertEqual((self.folder / 'saves' / 'save.sav').read_bytes(), b'preserve')
        self.assertEqual(self.link(candidate['token'])[1], 409)

    def test_changed_card_root_and_folder_refuse_without_mutation(self):
        token = self.find()['candidates'][0]['token']
        self.db.execute("update items set title='Changed' where id=1"); self.db.commit()
        self.assertEqual(self.link(token)[1], 409)
        self.db.execute("update items set title='Hidden Badge' where id=1"); self.db.commit()
        token = self.find()['candidates'][0]['token']
        self.cfg['games_root'] = str(self.root / 'new7')
        self.assertEqual(self.link(token)[1], 409)
        self.cfg['games_root'] = str(self.root)
        token = self.find()['candidates'][0]['token']
        (self.folder / 'new-file').write_bytes(b'test')
        self.assertEqual(self.link(token)[1], 409)
        self.assertEqual(self.row()['path'], '')

    def test_existing_path_or_other_card_prevents_association(self):
        token = self.find()['candidates'][0]['token']
        self.db.execute("insert into items(title,kind,path,url) values('Other','game',?,'game:other')", (str(self.folder),))
        self.db.commit()
        self.assertEqual(self.link(token)[1], 409)
        self.assertEqual(self.row()['path'], '')
        self.db.execute("update items set path='old-path' where id=1"); self.db.commit()
        self.assertNotIn('token', self.find()['candidates'][0])

    def test_archives_are_suggestions_only_and_links_skipped(self):
        (self.root / 'HiddenBadge_20260828c.zip').write_bytes(b'not inspected')
        try:
            (self.root / 'Hidden Badge').symlink_to(self.folder, target_is_directory=True)
        except OSError:
            pass
        result = self.find()
        archive = next(c for c in result['candidates'] if c['kind'] == 'archive')
        self.assertNotIn('token', archive)
        self.assertFalse(any(c['path'] == str(self.root / 'Hidden Badge') for c in result['candidates']))

    def test_ownership_snapshot_exposes_other_cards_without_link_tokens(self):
        self.db.execute("insert into items(id,title,kind,path,url) values(2,'Другой вариант','game',?,'game:other')", (str(self.folder),))
        self.db.commit()
        candidate = self.find()['candidates'][0]
        self.assertEqual(candidate['association'], {'state': 'other', 'cards': [{'id': 2, 'title': 'Другой вариант'}], 'extra': 0})
        self.assertNotIn('token', candidate)
        self.assertEqual(self.row()['path'], '')
        self.db.execute('update items set path=? where id=1', (str(self.folder),)); self.db.commit()
        candidate = self.find()['candidates'][0]
        self.assertEqual(candidate['association']['state'], 'multiple')
        self.assertEqual({c['id'] for c in candidate['association']['cards']}, {1, 2})
        self.db.execute('delete from items where id=2'); self.db.commit()
        self.assertEqual(self.find()['candidates'][0]['association']['state'], 'this')

    def test_ownership_display_is_bounded_and_query_errors_are_unknown(self):
        for i in range(2, 9):
            self.db.execute('insert into items(id,title,kind,path,url) values(?,?,?,?,?)',
                            (i, f'Card {i}', 'game', str(self.folder), f'game:{i}'))
        self.db.commit()
        candidate = self.find()['candidates'][0]
        self.assertEqual(candidate['association']['state'], 'multiple')
        self.assertEqual(len(candidate['association']['cards']), 5)
        self.assertEqual(candidate['association']['extra'], 2)
        self.db.execute('drop table items'); self.db.commit()
        result = game_associations.associations(self.db, self.lock, [candidate], 1)
        self.assertEqual(result[0]['state'], 'unknown')

    def test_incomplete_ownership_never_offers_binding(self):
        self.db.execute("insert into items(id,title,kind,path,url) values(2,'Other','game',?,'game:other')", (str(self.root / 'other'),))
        self.db.commit()
        with patch.object(game_associations, 'MAX_ROWS', 0):
            candidate = self.find()['candidates'][0]
        self.assertEqual(candidate['association']['state'], 'unknown')
        self.assertNotIn('token', candidate)
        self.db.execute("update items set info='uncommitted' where id=1")
        try:
            candidate = self.find()['candidates'][0]
            self.assertEqual(candidate['association']['state'], 'unknown')
            self.assertNotIn('token', candidate)
            self.assertTrue(self.db.in_transaction)
        finally:
            self.db.rollback()

    def test_search_does_not_depend_on_direntry_stat_identity(self):
        # On Windows DirEntry.stat may omit identity fields used by os.stat.
        original = os.scandir
        class Entry:
            def __init__(self, entry): self.entry = entry
            def __getattr__(self, name): return getattr(self.entry, name)
            def stat(self, *args, **kwargs): raise AssertionError('DirEntry identity is not portable')
        class Scan:
            def __init__(self, path): self.iterator = original(path)
            def __enter__(self): return (Entry(entry) for entry in self.iterator)
            def __exit__(self, *args): self.iterator.close()
        with patch('storage.local_game_search.os.scandir', side_effect=Scan):
            token = self.find()['candidates'][0]['token']
        self.assertEqual(self.link(token)[1], 200)

    def test_search_limits_and_wrong_id_are_explicit(self):
        with patch.object(local_game_search, 'MAX_ENTRIES', 1):
            result = self.find()
            self.assertTrue(result['incomplete'])
            self.assertLessEqual(result['scanned'], 1)
        token = self.find()['candidates'][0]['token']
        self.assertEqual(self.link(token, item_id=2)[1], 409)
        self.assertEqual(self.row()['path'], '')

    def test_corrupt_or_conflicting_metadata_is_not_overwritten(self):
        for value in ('not-json', json.dumps({'inst': {'path': str(self.root / 'other')}})):
            self.db.execute('update items set info=? where id=1', (value,)); self.db.commit()
            token = self.find()['candidates'][0]['token']
            self.assertEqual(self.link(token)[1], 409)
            self.assertEqual(self.row()['info'], value)
            self.assertEqual(self.row()['path'], '')
