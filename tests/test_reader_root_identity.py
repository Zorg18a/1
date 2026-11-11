"""Reader root identity fences on temporary, unmigrated SQLite databases."""
import json
from pathlib import Path
import re
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from core import reader_images
from core.legacy_reader_progress import progress_request
from storage import reader_manifest, reader_snapshot
from storage.database import execute, open_database


class ReaderRootIdentityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name); self.first = self.base / 'first'; self.second = self.base / 'second'
        manifest = {'slug': 'same', 'title': 'Test', 'listed': [], 'chapters': {}}
        for folder in (self.first, self.second):
            folder.mkdir(); (folder / 'manifest.json').write_text(json.dumps(manifest), encoding='utf8')
        self.db, self.lock = open_database(self.base / 'library.db')
        self.db.execute("insert into items(id,kind,url,root) values(1,'manga','manga:same',?)", (str(self.first),))
        self.db.execute("insert into progress values('same','1',0)"); self.db.commit()

    def tearDown(self):
        self.db.close(); self.tmp.cleanup()

    def read(self):
        return reader_manifest.manga_info(1, lambda statement, args: execute(self.db, self.lock, statement, args))

    def request(self, **extra):
        return progress_request({'id': 1, 'cid': '2', 'page': 1, 'slug': 'same', **extra}, self.db, self.lock)

    def test_changed_root_with_same_slug_blocks_save_and_does_not_expose_path(self):
        original = self.read(); identity = original['progress_identity']
        self.assertEqual(len(identity), 64); self.assertNotIn(str(self.first), json.dumps(original))
        other = sqlite3.connect(self.base / 'library.db')
        try:
            other.execute('update items set root=? where id=1', (str(self.second),)); other.commit()
        finally:
            other.close()
        current = self.read()
        self.assertEqual(current['progress_slug'], original['progress_slug'])
        self.assertEqual(current['progress_snapshot'], original['progress_snapshot'])
        self.assertNotEqual(current['progress_identity'], identity)
        result, status = self.request(snapshot=original['progress_snapshot'], identity=identity)
        self.assertEqual(status, 409); self.assertIn('error', result)
        self.assertEqual(tuple(self.db.execute('select cid,page from progress').fetchone()), ('1', 0))
        self.assertFalse(self.db.in_transaction)
        self.assertEqual(self.request(snapshot=current['progress_snapshot'], identity=current['progress_identity'])[1], 200)

    def test_image_identity_tracks_url_root_and_process_key(self):
        initial = self.read()['image_identity']
        self.assertNotEqual(initial, self.read()['progress_identity'])
        self.db.execute("update items set url='manga:different' where id=1"); self.db.commit()
        changed = self.read()
        self.assertFalse(changed['progress_save_allowed'])
        self.assertNotEqual(initial, changed['image_identity'])
        self.db.execute("update items set url='manga:same',root=? where id=1", (str(self.second),)); self.db.commit()
        self.assertNotEqual(initial, self.read()['image_identity'])
        self.db.execute('update items set root=? where id=1', (str(self.first),)); self.db.commit()
        self.assertEqual(initial, self.read()['image_identity'])  # Value ABA cannot be detected.
        with patch.object(reader_snapshot, '_KEY', b'new-process-key'):
            self.assertNotEqual(initial, self.read()['image_identity'])

    def test_image_uses_the_checked_root_if_record_changes_after_query(self):
        identity = self.read()['image_identity']
        def sql(statement, args):
            rows = execute(self.db, self.lock, statement, args)
            execute(self.db, self.lock, 'update items set root=? where id=1', (str(self.second),))
            return rows
        class Handler:
            def file(self, path): return path
            def js(self, body, status): raise AssertionError((status, body))
            def send_error(self, status): raise AssertionError(status)
        match = re.fullmatch(r'/mi/(\d+)/(\d+)/(\d{3}\.\w+)', '/mi/1/12/001.png')
        result = reader_images.get(Handler(), match, 'identity=' + identity, sql)
        self.assertEqual(result, self.first / 'chapters' / '12' / '001.png')
        self.assertEqual(self.db.execute('select root from items').fetchone()[0], str(self.second))

    def test_old_snapshot_clients_remain_compatible_and_bad_identity_is_rejected(self):
        data = self.read(); token = data['progress_snapshot']
        for identity in ('', None, 'x' * 64, 'a' * 63, True):
            self.assertEqual(self.request(snapshot=token, identity=identity)[1], 400)
        self.assertEqual(self.request(identity='a' * 64)[1], 400)
        self.db.execute('update items set root=? where id=1', (str(self.second),)); self.db.commit()
        self.assertEqual(self.request(snapshot=token)[1], 200)  # Older snapshot clients remain unconditional for root.

    def test_root_changing_trigger_is_rolled_back(self):
        self.db.execute("create trigger move_root after update on progress begin update items set root='changed' where id=1; end")
        self.db.commit(); data = self.read()
        self.assertEqual(self.request(snapshot=data['progress_snapshot'], identity=data['progress_identity'])[1], 409)
        self.assertEqual(self.db.execute('select root from items').fetchone()[0], str(self.first))
        self.assertEqual(tuple(self.db.execute('select cid,page from progress').fetchone()), ('1', 0))
        self.assertFalse(self.db.in_transaction)

    def test_process_secret_and_aba_limit(self):
        before = self.read()['progress_identity']
        self.db.execute('update items set root=? where id=1', (str(self.second),)); self.db.commit()
        self.assertNotEqual(before, self.read()['progress_identity'])
        self.db.execute('update items set root=? where id=1', (str(self.first),)); self.db.commit()
        self.assertEqual(before, self.read()['progress_identity'])  # Root ABA is not detected.
        with patch.object(reader_snapshot, '_KEY', b'another-process-key'):
            self.assertNotEqual(before, self.read()['progress_identity'])


if __name__ == '__main__':
    unittest.main()
