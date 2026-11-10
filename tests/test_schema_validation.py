"""Essential legacy constraints are checked before a startup schema is accepted."""
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from storage import playback_migration, schema_validation, startup_schema


ITEM_COLUMNS = 'title, author, topic, kind, path, root, url, size int, added default current_timestamp'
VALID_ITEMS = f'create table items(id integer primary key, {ITEM_COLUMNS}, unique(url))'
VALID_PROGRESS = 'create table progress(slug primary key, cid, page int)'
VALID_TAGS = ('create table game_tags(item_id integer not null, position integer not null, '
              'tag text not null, primary key(item_id, position))')
VALID_INBOX = ('create table inbox(id integer primary key, batch text, tab_id int, window_id int, '
               'url text, title text, kind text, host text, action text, state text, lib_id int, '
               "close_tab int, status text, reason text default '', jobs text default '[]', "
               "cmd text default '', created text default current_timestamp)")


class SchemaValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.backups = self.root / 'backups'
        self.backups.mkdir()
        self.db = sqlite3.connect(self.root / 'library.db')
        self.db.row_factory = sqlite3.Row

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def make_old(self, *, items=VALID_ITEMS, progress=VALID_PROGRESS, tags=VALID_TAGS,
                 inbox=VALID_INBOX, extra=()):
        for statement in (items, progress, tags, inbox, *extra):
            self.db.execute(statement)
        self.db.execute("insert into items(id,title,kind,url) values(1,'Old','video','old')")
        self.db.execute("insert into progress(slug,cid,page) values('s','c',12)")
        self.db.commit()

    def migrate(self):
        return playback_migration.migrate(self.db, self.backups, initialize=startup_schema.initialize,
                                          needs=startup_schema.requires_migration)

    def test_original_schema_and_explicit_unique_index_remain_compatible(self):
        self.make_old(items=f'create table items(id integer primary key, {ITEM_COLUMNS})',
                      extra=('create unique index items_url on items(url)',))
        snapshot = self.migrate()
        self.assertTrue(snapshot.is_file())
        self.assertFalse(startup_schema.requires_migration(self.db))
        self.assertEqual(self.db.execute('select page from progress').fetchone()[0], 12)
        self.assertIsNone(self.migrate())

    def test_incompatible_keys_reject_migration_and_leave_original_intact(self):
        cases = {
            'items text id': {'items': f'create table items(id text primary key, {ITEM_COLUMNS}, unique(url))'},
            'items desc id': {'items': f'create table items(id integer primary key desc, {ITEM_COLUMNS}, unique(url))'},
            'items without rowid': {'items': f'create table items(id integer primary key, {ITEM_COLUMNS}, unique(url)) without rowid'},
            'items composite key': {'items': f'create table items(id integer, {ITEM_COLUMNS}, primary key(id,url), unique(url))'},
            'missing url unique': {'items': f'create table items(id integer primary key, {ITEM_COLUMNS})'},
            'partial url unique': {'items': f'create table items(id integer primary key, {ITEM_COLUMNS})',
                                   'extra': ('create unique index partial_url on items(url) where url is not null',)},
            'composite url unique': {'items': f'create table items(id integer primary key, {ITEM_COLUMNS}, unique(url,kind))'},
            'nocase url unique': {'items': f'create table items(id integer primary key, {ITEM_COLUMNS}, unique(url collate nocase))'},
            'progress missing key': {'progress': 'create table progress(slug, cid, page int)'},
            'progress composite key': {'progress': 'create table progress(slug, cid, page int, primary key(slug,cid))'},
            'tags wrong order': {'tags': ('create table game_tags(item_id integer not null, position integer not null, '
                                          'tag text not null, primary key(position,item_id))')},
            'tags nullable': {'tags': ('create table game_tags(item_id integer, position integer not null, '
                                      'tag text not null, primary key(item_id,position))')},
            'tags wrong type': {'tags': ('create table game_tags(item_id text not null, position integer not null, '
                                        'tag text not null, primary key(item_id,position))')},
            'inbox int id': {'inbox': VALID_INBOX.replace('id integer primary key', 'id int primary key')},
        }
        for name, kwargs in cases.items():
            with self.subTest(name=name):
                self.db.close()
                path = self.root / 'library.db'
                path.unlink(missing_ok=True)
                for backup in self.backups.iterdir():
                    backup.unlink()
                self.db = sqlite3.connect(path)
                self.db.row_factory = sqlite3.Row
                self.make_old(**kwargs)
                original = list(self.db.iterdump())
                with self.assertRaises(sqlite3.DatabaseError):
                    self.migrate()
                self.assertFalse(self.db.in_transaction)
                self.assertEqual(list(self.db.iterdump()), original)
                snapshots = list(self.backups.glob('*.db'))
                self.assertEqual(len(snapshots), 1)
                with closing(sqlite3.connect(snapshots[0])) as backup:
                    self.assertEqual(backup.execute('select page from progress').fetchone()[0], 12)
                    self.assertEqual(backup.execute('pragma integrity_check').fetchone()[0], 'ok')

    def test_complete_incompatible_schema_cannot_be_mistaken_for_current(self):
        self.make_old(items=f'create table items(id integer primary key, {ITEM_COLUMNS})')
        with patch.object(schema_validation, 'validate'):
            self.migrate()
        backups_before = set(self.backups.iterdir())
        with self.assertRaisesRegex(sqlite3.DatabaseError, 'уникальность url'):
            self.migrate()
        self.assertFalse(self.db.in_transaction)
        self.assertEqual(set(self.backups.iterdir()), backups_before)
        self.assertEqual(self.db.execute('select title from items').fetchone()[0], 'Old')

    def test_extra_columns_and_indexes_are_preserved(self):
        self.make_old(extra=('alter table items add column custom text',
                             'create index custom_index on items(custom)'))
        self.db.execute("update items set custom='keep'")
        self.db.commit()
        self.migrate()
        self.assertEqual(self.db.execute('select custom from items').fetchone()[0], 'keep')
        self.assertIsNotNone(self.db.execute("select name from sqlite_master where name='custom_index'").fetchone())
