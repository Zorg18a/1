"""Backup-first revision migration checks on temporary databases, never startup."""
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest

from storage import playback_migration, reader_revision
from storage.database import open_database


class RevisionMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db, self.lock = open_database(self.root / 'library.db')
        self.backups = self.root / 'backups'; self.backups.mkdir()
        self.db.execute("insert into items(id,kind,url) values(1,'manga','manga:foo')")
        self.db.execute("insert into progress values('foo','chapter',7)")
        self.db.commit()

    def tearDown(self):
        self.db.close(); self.temp.cleanup()

    def migrate(self):
        return playback_migration.migrate(self.db, self.backups, initialize=reader_revision.initialize,
                                          needs=reader_revision.requires_migration)

    def test_backup_once_repeat_and_reopen_preserve_revisions(self):
        self.db.execute('pragma journal_mode=wal')
        snapshot = self.migrate()
        old = reader_revision.read(self.db, self.lock, 1)
        with closing(sqlite3.connect(snapshot)) as backup:
            self.assertEqual(backup.execute('select cid,page from progress').fetchone(), ('chapter', 7))
            self.assertIsNone(backup.execute("select name from sqlite_master where name='mediahub_reader_revision'").fetchone())
            self.assertEqual(backup.execute('pragma integrity_check').fetchone()[0], 'ok')
        self.assertIsNone(self.migrate())
        with closing(sqlite3.connect(self.root / 'library.db')) as reopened:
            self.assertEqual(reader_revision.read(reopened, threading.Lock(), 1), old)
        self.assertEqual(len(list(self.backups.glob('*.db'))), 1)

    def test_partial_revision_schema_is_never_repaired(self):
        self.migrate()
        self.db.execute('drop trigger mediahub_reader_progress_update_new'); self.db.commit()
        with self.assertRaises(sqlite3.DatabaseError): self.migrate()
        self.assertEqual(len(list(self.backups.glob('*.db'))), 1)
        self.assertIsNone(self.db.execute("select name from sqlite_master where name='mediahub_reader_progress_update_new'").fetchone())
        self.assertEqual(self.db.execute('select page from progress').fetchone()[0], 7)

    def test_conflicting_object_and_missing_or_corrupt_token_fail_closed(self):
        self.db.execute('create table mediahub_reader_progress_insert_new(x)'); self.db.commit()
        with self.assertRaises(sqlite3.DatabaseError): self.migrate()
        self.assertEqual(list(self.backups.iterdir()), [])
        self.db.execute('drop table mediahub_reader_progress_insert_new'); self.db.commit()
        self.migrate()
        original = reader_revision.read(self.db, self.lock, 1)['token']
        for token in ('bad', 'a' * 32 + '\x00extra'):
            self.db.execute('update mediahub_reader_revision set token=? where slug=?', (token, 'foo')); self.db.commit()
            with self.assertRaises(sqlite3.DatabaseError): self.migrate()
            with self.assertRaises(sqlite3.DatabaseError): reader_revision.read(self.db, self.lock, 1)
        self.db.execute('update mediahub_reader_revision set token=? where slug=?', (original, 'foo')); self.db.commit()
        self.db.execute("delete from mediahub_reader_revision where slug='foo'"); self.db.commit()
        with self.assertRaises(sqlite3.DatabaseError): self.migrate()
        self.assertEqual(len(list(self.backups.glob('*.db'))), 1)

    def test_wal_busy_writer_prevents_backup_and_schema_changes(self):
        self.db.execute('pragma journal_mode=wal')
        self.db.execute('pragma busy_timeout=10')
        with closing(sqlite3.connect(self.root / 'library.db')) as writer:
            writer.execute('begin immediate')
            writer.execute("update progress set page=8 where slug='foo'")
            with self.assertRaises(sqlite3.OperationalError): self.migrate()
            self.assertFalse(self.db.in_transaction)
            self.assertEqual(list(self.backups.iterdir()), [])
            writer.rollback()
        self.assertEqual(self.db.execute('select page from progress').fetchone()[0], 7)
        self.assertIsNotNone(self.migrate())

    def test_no_backup_or_write_with_bad_progress_primary_key(self):
        for declaration in ('slug TEXT COLLATE NOCASE PRIMARY KEY', 'slug NUMERIC PRIMARY KEY',
                            'slug INTEGER PRIMARY KEY'):
            self.db.execute('drop table progress')
            self.db.execute(f'create table progress({declaration},cid,page int)'); self.db.commit()
            with self.subTest(declaration=declaration), self.assertRaises(sqlite3.DatabaseError): self.migrate()
            self.assertEqual(list(self.backups.iterdir()), [])
            self.assertIsNone(self.db.execute("select name from sqlite_master where name='mediahub_reader_revision'").fetchone())

    def test_additional_unique_index_is_rejected_before_and_after_migration(self):
        self.db.execute('create unique index unique_cid on progress(cid)'); self.db.commit()
        with self.assertRaises(sqlite3.DatabaseError): self.migrate()
        self.assertEqual(list(self.backups.iterdir()), [])
        self.db.execute('drop index unique_cid'); self.db.commit(); self.migrate()
        before = reader_revision.read(self.db, self.lock, 1)
        self.db.execute('create unique index unique_cid on progress(cid)'); self.db.commit()
        with self.assertRaises(sqlite3.DatabaseError): self.migrate()
        with self.assertRaises(sqlite3.DatabaseError):
            reader_revision.write(self.db, self.lock, 1, before['slug'], before['token'], 'new', 8)
        self.assertEqual(self.db.execute('select page from progress').fetchone()[0], 7)

    def test_binary_key_with_nocase_column_uses_binary_snapshots(self):
        self.db.execute('drop table progress')
        self.db.execute('create table progress(slug TEXT COLLATE NOCASE, cid, page, primary key(slug collate binary))')
        self.db.execute("insert into progress values('Foo','upper',1)")
        self.db.execute("insert into progress values('foo','lower',2)")
        self.db.commit(); self.migrate()
        before = reader_revision.read(self.db, self.lock, 1)
        self.assertEqual(before['progress']['cid'], 'lower')
        after = reader_revision.write(self.db, self.lock, 1, before['slug'], before['token'], 'new', 3)
        self.assertNotEqual(after['token'], before['token'])
        self.assertEqual(self.db.execute("select cid from progress where slug='Foo' collate binary").fetchone()[0], 'upper')
        with self.assertRaises(reader_revision.Conflict):
            reader_revision.write(self.db, self.lock, 1, before['slug'], before['token'], 'late', 4)
        self.assertIsNone(self.migrate())

    def test_sentinel_rows_remain_and_validate_after_deletion(self):
        self.migrate()
        self.db.execute("delete from progress where slug='foo'")
        self.db.execute('delete from items where id=1'); self.db.commit()
        self.assertEqual(self.db.execute('select count(*) from mediahub_reader_revision').fetchone()[0], 1)
        self.assertIsNone(self.migrate())

    def test_requires_migration_needs_caller_transaction(self):
        with self.assertRaises(ValueError): reader_revision.requires_migration(self.db)
