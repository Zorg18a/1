import sqlite3
import tempfile
import unittest
from pathlib import Path
from storage.database import execute, open_database


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'library.db'
        self.db, self.lock = open_database(self.path)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_persistence_and_unique_url(self):
        execute(self.db, self.lock, 'insert into items(title,url) values(?,?)', ('Title', 'https://example.org'))
        with self.assertRaises(sqlite3.IntegrityError):
            execute(self.db, self.lock, 'insert into items(title,url) values(?,?)', ('Other', 'https://example.org'))
        self.db.close()
        self.db, self.lock = open_database(self.path)
        self.assertEqual(execute(self.db, self.lock, 'select title from items')[0]['title'], 'Title')

    def test_migrates_old_table_without_losing_rows(self):
        self.db.close()
        self.path.unlink()
        old = sqlite3.connect(self.path)
        old.execute('create table items(id integer primary key, title, url unique)')
        old.execute('insert into items(title,url) values (?,?)', ('Old', 'url'))
        old.commit()
        old.close()
        self.db, self.lock = open_database(self.path)
        row = execute(self.db, self.lock, 'select title,thumb from items')[0]
        self.assertEqual((row['title'], row['thumb']), ('Old', None))
