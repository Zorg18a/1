"""One-shot extra-root searches are bounded, read-only and never issue link tokens."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core import local_game_match, update_preview
from legacy import gamesweep
from storage import extra_game_root, local_game_search
from storage.database import open_database


class ExtraGameSearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / 'extra'
        self.folder = self.root / 'category' / 'HiddenBadge_20260828c'
        (self.folder / 'saves').mkdir(parents=True)
        (self.folder / 'saves' / 'slot.sav').write_bytes(b'keep')
        self.db, self.lock = open_database(Path(self.tmp.name) / 'library.db')
        self.db.execute('alter table items add column info')
        self.db.execute("insert into items(id,title,kind,path,url,info) values(1,'Hidden Badge','game','','game:hiddenbadge','{}')")
        self.db.commit()
        self.row = self.db.execute('select * from items where id=1').fetchone()

    def tearDown(self):
        self.db.close(); self.tmp.cleanup()

    def request(self, root):
        return update_preview.preview_request({'id': 1, 'mode': 'local_search_other', 'root': root},
            lambda i: self.row if i == 1 else None, lambda row: {}, gamesweep.parse_name,
            '', str(Path(self.tmp.name) / 'configured'), self.db, self.lock, {'games_root': str(self.root)})

    def test_extra_root_finds_but_never_offers_a_link_or_changes_data(self):
        data, status = self.request(str(self.root))
        self.assertEqual(status, 200, data)
        candidate = next(c for c in data['candidates'] if c['path'] == str(self.folder))
        self.assertEqual(candidate['association']['state'], 'none')
        self.assertNotIn('token', candidate)
        self.assertNotIn('identity', candidate)
        self.assertEqual(self.db.execute('select path,info from items where id=1').fetchone()['path'], '')
        self.assertEqual((self.folder / 'saves' / 'slot.sav').read_bytes(), b'keep')
        self.assertEqual(local_game_match.link({'id': 1, 'token': 'fake'}, self.db, self.lock,
                                              {'games_root': str(self.root)})[1], 409)

    def test_other_card_and_limits_are_shown(self):
        self.db.execute("insert into items(id,title,kind,path,url) values(2,'Other','game',?,'game:other')", (str(self.folder),))
        self.db.commit()
        data, status = self.request(str(self.root))
        self.assertEqual(status, 200)
        self.assertEqual(data['candidates'][0]['association']['cards'][0]['id'], 2)
        with patch.object(local_game_search, 'MAX_ENTRIES', 1):
            data, status = self.request(str(self.root))
        self.assertEqual(status, 200); self.assertTrue(data['incomplete'])

    def test_invalid_missing_or_linked_root_is_rejected(self):
        for value in (None, 5, '', 'relative', ' /tmp', '/tmp\0bad', '/tmp\nfoo', '/' + 'a' * 2049):
            with self.subTest(value=value): self.assertEqual(self.request(value)[1], 400)
        self.assertEqual(self.request(str(self.root / 'missing'))[1], 400)
        try:
            link = Path(self.tmp.name) / 'link'
            link.symlink_to(self.root, target_is_directory=True)
        except OSError:
            return
        self.assertEqual(self.request(str(link))[1], 400)

    @unittest.skipUnless(os.name == 'nt', 'Windows path rules')
    def test_windows_network_device_and_drive_relative_paths_rejected(self):
        for value in (r'\\server\share\games', r'\\?\C:\games', r'C:games', r'\games'):
            with self.subTest(value=value):
                with self.assertRaises(ValueError): extra_game_root.validate_root(value)
