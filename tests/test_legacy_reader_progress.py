"""Current reader writer preserves unrelated data and never changes the schema."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from core.legacy_reader_progress import progress_request
from storage.database import open_database


class LegacyReaderProgressTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db, self.lock = open_database(Path(self.temp.name) / 'test.db')
        self.db.execute("insert into items(id,kind,url) values(1,'manga','manga:slug'), (2,'video','video:slug')")
        self.db.execute("insert into progress(slug,cid,page) values('slug','old',4)")
        self.db.commit()

    def tearDown(self):
        self.db.close(); self.temp.cleanup()

    def request(self, **data):
        return progress_request(data, self.db, self.lock)

    def test_old_schema_and_legacy_chapter_ids(self):
        before = [tuple(row) for row in self.db.execute('pragma table_info(progress)')]
        self.assertEqual(self.request(id='1', cid='chapter-special', page='7'), ({'ok': 1}, 200))
        self.assertEqual(tuple(self.db.execute("select cid,page from progress where slug='slug'").fetchone()), ('chapter-special', 7))
        self.assertEqual([tuple(row) for row in self.db.execute('pragma table_info(progress)')], before)

    def test_missing_wrong_kind_and_bad_input_never_write(self):
        for data, status in [({'id': 2, 'cid': '1', 'page': 0}, 404),
                             ({'id': 999, 'cid': '1', 'page': 0}, 404),
                             ({'id': 1, 'cid': '', 'page': 0}, 400),
                             ({'id': True, 'cid': '1', 'page': 0}, 400),
                             ({'id': 1, 'cid': True, 'page': 0}, 400),
                             ({'id': 1, 'cid': '1', 'page': 2**63}, 400)]:
            self.assertEqual(self.request(**data)[1], status)
        self.assertEqual(tuple(self.db.execute("select cid,page from progress where slug='slug'").fetchone()), ('old', 4))
        self.assertEqual(self.db.execute('select count(*) from progress').fetchone()[0], 1)

    def test_upsert_preserves_extra_data_and_invalidates_stale_timestamp(self):
        self.db.execute('alter table progress add column updated real')
        self.db.execute("alter table progress add column custom text default 'initial'")
        self.db.execute("update progress set updated=100,custom='keep' where slug='slug'")
        self.db.commit()
        self.assertEqual(self.request(id=1, cid='new', page=8)[1], 200)
        self.assertEqual(tuple(self.db.execute("select cid,page,updated,custom from progress where slug='slug'").fetchone()),
                         ('new', 8, None, 'keep'))

    def test_expected_slug_rejects_changed_identity_without_modifying_either_row(self):
        self.db.execute("insert into progress values('other','previous',9)")
        self.db.execute("update items set url='manga:other' where id=1"); self.db.commit()
        data, status = self.request(id=1, cid='new', page=6, slug='slug')
        self.assertEqual(status, 409); self.assertIn('error', data)
        self.assertFalse(self.db.in_transaction)
        rows = {r['slug']: (r['cid'], r['page']) for r in self.db.execute('select * from progress')}
        self.assertEqual(rows, {'slug': ('old', 4), 'other': ('previous', 9)})
        self.assertEqual(self.request(id=1, cid='new', page=6, slug='other')[1], 200)
        self.assertEqual(self.db.execute("select page from progress where slug='other'").fetchone()[0], 6)

    def test_expected_slug_validation_and_old_client_compatibility(self):
        for slug in (None, '', True, 'x\0y', 'x' * 1025):
            self.assertEqual(self.request(id=1, cid='1', page=0, slug=slug)[1], 400)
        self.assertEqual(self.request(id=1, cid='legacy', page=1)[1], 200)
        self.assertEqual(self.db.execute("select cid from progress where slug='slug'").fetchone()[0], 'legacy')
        self.assertEqual(self.request(id=999, cid='1', page=0, slug='slug')[1], 404)

    def test_write_failure_is_reported_and_rolled_back(self):
        self.db.execute("create trigger deny_progress before update on progress begin select raise(abort, 'denied'); end")
        self.db.commit()
        with self.assertLogs(level='ERROR'):
            data, status = self.request(id=1, cid='12', page=1)
        self.assertEqual(status, 500); self.assertIn('error', data)
        self.assertFalse(self.db.in_transaction)
        self.assertEqual(tuple(self.db.execute("select cid,page from progress where slug='slug'").fetchone()), ('old', 4))
        self.assertEqual(self.db.execute('pragma integrity_check').fetchone()[0], 'ok')
