"""Inspect uploaded snapshots in memory, without operating on the live database."""
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from storage import backup_download, backup_restore
from storage.database import open_database


class InspectBytesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db, self.lock = open_database(self.root / 'library.db')
        self.db.execute("insert into items(id,title,kind,url) values(1,'Тест','video','test')")
        self.db.execute("insert into progress values('manga','3',5)")
        self.db.commit()

    def tearDown(self):
        self.db.close(); self.temp.cleanup()

    def test_exported_snapshot_is_checked_without_modifying_source(self):
        self.db.execute('pragma journal_mode=wal')
        self.db.execute("update progress set page=8 where slug='manga'"); self.db.commit()
        image = backup_download.snapshot(self.db, self.lock)
        self.assertEqual(backup_restore.inspect_bytes(image), {'items': 1, 'progress': 1})
        self.assertEqual(self.db.execute('select page from progress').fetchone()[0], 8)
        self.assertFalse((self.root / 'restored.db').exists())

    def test_invalid_or_wal_images_are_rejected(self):
        image = backup_download.snapshot(self.db, self.lock)
        for value in (b'', b'hello', b'x' * 100, image[:100], image[:18] + b'\2\2' + image[20:]):
            with self.subTest(size=len(value)), self.assertRaises(backup_restore.RestoreError):
                backup_restore.inspect_bytes(value)
        with self.assertRaises(backup_restore.RestoreError):
            backup_restore.inspect_bytes(image, max_bytes=100)
        with self.assertRaises(backup_restore.RestoreError):
            backup_restore.inspect_bytes(bytearray(image))

    def test_integrity_does_not_imply_schema_compatibility(self):
        with closing(sqlite3.connect(':memory:')) as db:
            db.execute('create table unrelated(id integer)')
            data = db.serialize()
        with self.assertRaises(backup_restore.RestoreError): backup_restore.inspect_bytes(data)
        image = backup_download.snapshot(self.db, self.lock)
        with self.assertRaises(backup_restore.RestoreError): backup_restore.inspect_bytes(image, timeout=-1)
