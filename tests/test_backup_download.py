"""In-memory downloads use only temporary databases in tests."""
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from storage import backup_download
from storage.database import open_database


class BackupDownloadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db, self.lock = open_database(self.root / 'original.db')
        self.db.execute("insert into items(id,title,kind,url) values(1,'Личное','video','example')")
        self.db.commit()

    def tearDown(self):
        self.db.close(); self.temp.cleanup()

    def test_wal_snapshot_reopens_without_wal_in_read_only_mode(self):
        self.db.execute('pragma journal_mode=wal')
        self.db.execute('pragma wal_autocheckpoint=0')
        self.db.execute("update items set title='Из WAL' where id=1"); self.db.commit()
        image = backup_download.snapshot(self.db, self.lock)
        self.assertEqual(image[:16], b'SQLite format 3\0')
        self.assertEqual(image[18:20], b'\x01\x01')
        path = self.root / 'download.db'; path.write_bytes(image)
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as copy:
            self.assertEqual(copy.execute('select title from items').fetchone()[0], 'Из WAL')
            self.assertEqual(copy.execute('pragma integrity_check').fetchone()[0], 'ok')
            self.assertEqual(copy.execute('pragma journal_mode').fetchone()[0], 'delete')
        self.assertFalse(Path(str(path) + '-wal').exists())
        self.assertEqual(self.db.execute('select title from items').fetchone()[0], 'Из WAL')

    def test_regular_snapshot_and_size_limit(self):
        self.assertEqual(backup_download.snapshot(self.db, self.lock)[18:20], b'\x01\x01')
        with patch.object(backup_download, 'MAX_BYTES', 1):
            with self.assertRaises(backup_download.BackupError): backup_download.snapshot(self.db, self.lock)
        self.assertEqual(self.db.execute('select count(*) from items').fetchone()[0], 1)

    def test_active_transaction_not_committed_or_rolled_back(self):
        self.db.execute("update items set title='pending' where id=1")
        with self.assertRaises(backup_download.BackupError): backup_download.snapshot(self.db, self.lock)
        self.assertTrue(self.db.in_transaction)
        self.db.rollback()
        self.assertEqual(self.db.execute('select title from items').fetchone()[0], 'Личное')

    def test_timeout_does_not_damage_source(self):
        with patch.object(backup_download, 'TIMEOUT', -1):
            with self.assertRaises(backup_download.BackupError): backup_download.snapshot(self.db, self.lock)
        self.assertEqual(self.db.execute('pragma integrity_check').fetchone()[0], 'ok')
        self.assertEqual(self.db.execute('select title from items').fetchone()[0], 'Личное')
