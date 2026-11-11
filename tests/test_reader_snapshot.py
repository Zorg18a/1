"""Value-based optimistic reader snapshots on temporary, unmigrated databases."""
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from core.legacy_reader_progress import progress_request
from storage import reader_snapshot
from storage.database import open_database


class ReaderSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'test.db'
        self.db, self.lock = open_database(self.path)
        self.db.execute("insert into items(id,kind,url) values(1,'manga','manga:one')")
        self.db.commit()

    def tearDown(self):
        self.db.close(); self.temp.cleanup()

    def snapshot(self):
        row = self.db.execute("select cid,page from progress where slug='one'").fetchone()
        return reader_snapshot.token(1, 'one', row)

    def write(self, token, cid='12', page=1):
        return progress_request({'id': 1, 'cid': cid, 'page': page, 'slug': 'one', 'snapshot': token}, self.db, self.lock)

    def test_save_changes_snapshot_and_stale_retry_does_not_overwrite(self):
        original = self.snapshot()
        result, status = self.write(original)
        self.assertEqual(status, 200); self.assertEqual(result['snapshot'], self.snapshot())
        self.assertNotEqual(original, result['snapshot'])
        self.assertEqual(self.write(original, '13', 2)[1], 409)
        self.assertEqual(tuple(self.db.execute('select cid,page from progress').fetchone()), ('12', 1))
        result, status = self.write(result['snapshot'], '13', 2)
        self.assertEqual(status, 200); self.assertEqual(result['snapshot'], self.snapshot())
        self.assertFalse(self.db.in_transaction)

    def test_external_legacy_change_and_restart_reject_stale_tokens(self):
        initial = self.snapshot()
        other = sqlite3.connect(self.path)
        try:
            other.execute("insert into progress values('one','other',8)"); other.commit()
        finally:
            other.close()
        self.assertEqual(self.write(initial)[1], 409)
        current = self.snapshot()
        with patch.object(reader_snapshot, '_KEY', b'new-process-key'):
            self.assertEqual(self.write(current)[1], 409)
        self.assertEqual(tuple(self.db.execute('select cid,page from progress').fetchone()), ('other', 8))

    def test_concurrent_writes_use_database_lock_across_connections(self):
        initial = self.snapshot(); barrier = threading.Barrier(3); results = []
        def worker(cid):
            db = sqlite3.connect(self.path, timeout=5)
            try:
                barrier.wait()
                result = progress_request({'id': 1, 'cid': cid, 'page': 1, 'slug': 'one', 'snapshot': initial}, db, threading.Lock())
                results.append((cid, result[1]))
            finally:
                db.close()
        threads = [threading.Thread(target=worker, args=(cid,)) for cid in ('first', 'second')]
        for thread in threads: thread.start()
        barrier.wait()
        for thread in threads: thread.join(10); self.assertFalse(thread.is_alive())
        self.assertEqual(sorted(status for _, status in results), [200, 409])
        winner = next(cid for cid, status in results if status == 200)
        self.assertEqual(self.db.execute('select cid from progress').fetchone()[0], winner)

    def test_aba_is_not_detected_and_values_are_typed(self):
        self.db.execute("insert into progress values('one','a',1)"); self.db.commit()
        initial = self.snapshot()
        self.db.execute("update progress set cid='b' where slug='one'"); self.db.commit()
        self.assertNotEqual(initial, self.snapshot())
        self.db.execute("update progress set cid='a' where slug='one'"); self.db.commit()
        self.assertEqual(initial, self.snapshot())  # No stored revision: ABA is indistinguishable.
        self.assertNotEqual(reader_snapshot.token(1, 'one', ('1', 0)), reader_snapshot.token(1, 'one', (1, 0)))
        self.assertNotEqual(reader_snapshot.token(1, 'one', None), reader_snapshot.token(1, 'one', (None, None)))
        self.assertNotEqual(reader_snapshot.token(1, 'one', (b'x', 0)), reader_snapshot.token(1, 'one', ('x', 0)))
        self.assertNotEqual(initial, reader_snapshot.token(2, 'one', ('a', 1)))

    def test_invalid_snapshot_and_missing_or_changed_item(self):
        token = self.snapshot()
        for data in ({'snapshot': None, 'slug': 'one'}, {'snapshot': 'a' * 64},
                     {'snapshot': 'z' * 64, 'slug': 'one'}, {'snapshot': 'a' * 63, 'slug': 'one'}):
            self.assertEqual(progress_request({'id': 1, 'cid': '1', 'page': 0, **data}, self.db, self.lock)[1], 400)
        self.db.execute("update items set url='manga:two' where id=1"); self.db.commit()
        self.assertEqual(self.write(token)[1], 409)
        self.db.execute('delete from items'); self.db.commit()
        self.assertEqual(self.write(token)[1], 404)
        self.assertEqual(self.db.execute('select count(*) from progress').fetchone()[0], 0)

    def test_trigger_failure_rolls_back(self):
        self.db.execute("create trigger deny before insert on progress begin select raise(abort, 'denied'); end")
        self.db.commit(); token = self.snapshot()
        with self.assertLogs(level='ERROR'):
            self.assertEqual(self.write(token)[1], 500)
        self.assertFalse(self.db.in_transaction)
        self.assertEqual(token, self.snapshot())


if __name__ == '__main__':
    unittest.main()
