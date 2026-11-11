"""Manga manifest and library identities on temporary files and database."""
import json
from pathlib import Path
import tempfile
import unittest

from core.legacy_reader_progress import progress_request
from storage.database import execute, open_database
from storage.reader_manifest import manga_info


class ReaderManifestIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db, self.lock = open_database(self.root / 'library.db')
        self.db.execute("insert into items(id,kind,url,root) values(1,'manga','manga:alpha',?)", (str(self.root),))
        self.db.execute("insert into progress values('alpha','2',3)")
        self.db.execute("insert into progress values('beta','3',4)")
        self.db.commit()

    def tearDown(self):
        self.db.close(); self.temp.cleanup()

    def read(self, slug):
        manifest = {'title': 'Тест', 'slug': slug, 'listed': [{'cid': '2', 'label': 'Глава 2'}],
                    'chapters': {'2': {'label': 'Глава 2', 'files': ['001.png'], 'done': True}}}
        (self.root / 'manifest.json').write_text(json.dumps(manifest), encoding='utf8')
        return manga_info(1, lambda statement, args: execute(self.db, self.lock, statement, args))

    def test_matching_identity_can_write_and_preserves_read_position(self):
        result = self.read('alpha')
        self.assertTrue(result['progress_save_allowed']); self.assertEqual(result['progress_slug'], 'alpha')
        self.assertEqual(result['progress'], {'cid': '2', 'page': 3})
        self.assertEqual(result['chapters'][0]['files'], ['001.png'])

    def test_mismatch_is_read_only_and_prior_positions_are_untouched(self):
        result = self.read('beta')
        self.assertFalse(result['progress_save_allowed']); self.assertIsNone(result['progress_slug'])
        self.assertEqual(result['progress'], {'cid': '3', 'page': 4})
        self.assertEqual(self.db.execute('select count(*) from progress').fetchone()[0], 2)

    def test_invalid_slugs_fail_closed_and_still_expose_chapters(self):
        for slug in (None, '', True, 42, 'a\0b', 'x' * 1025):
            with self.subTest(slug=slug):
                result = self.read(slug)
                self.assertFalse(result['progress_save_allowed']); self.assertIsNone(result['progress_slug'])
                self.assertIsNone(result['progress']); self.assertEqual(result['have'], 1)

    def test_nocase_progress_collision_never_overwrites_another_slug(self):
        self.db.execute('drop table progress')
        self.db.execute('create table progress(slug TEXT COLLATE NOCASE PRIMARY KEY, cid, page int)')
        self.db.execute("insert into progress values('Alpha','other',9)"); self.db.commit()
        result = self.read('alpha')
        self.assertTrue(result['progress_save_allowed']); self.assertIsNone(result['progress'])
        body, status = progress_request({'id': 1, 'cid': '2', 'page': 0, 'slug': 'alpha'}, self.db, self.lock)
        self.assertEqual(status, 409); self.assertIn('error', body)
        self.assertEqual(tuple(self.db.execute('select slug,cid,page from progress').fetchone()), ('Alpha', 'other', 9))
        self.assertFalse(self.db.in_transaction)

    def test_url_must_match_case_and_prefix_exactly(self):
        for url in ('manga:ALPHA', 'file:alpha', 'manga:', None):
            self.db.execute('update items set url=? where id=1', (url,)); self.db.commit()
            self.assertFalse(self.read('alpha')['progress_save_allowed'])
