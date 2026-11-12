"""Protect manually associated game paths and reject stale card mutations."""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from core import game_card_settings
from storage import game_card_write
from storage.database import open_database


class GameCardWriteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db, self.lock = open_database(Path(self.tmp.name) / 'library.db')
        self.db.execute('alter table items add column src')
        self.db.execute('alter table items add column info')
        self.path = str(Path(self.tmp.name) / 'games' / 'Game')
        self.other = str(Path(self.tmp.name) / 'games' / 'Game v2')
        self.info = {'note': 'keep', 'mediahub_manual_game_path_v1': self.path, 'inst': {'path': self.path}}
        self.db.execute("insert into items(id,title,kind,path,url,info) values(1,'Game','game',?,'game:game',?)",
                        (self.path, json.dumps(self.info)))
        self.db.commit()

    def tearDown(self):
        self.db.close(); self.tmp.cleanup()

    def row(self): return self.db.execute('select * from items where id=1').fetchone()
    def update_scan(self, row, path):
        game_card_write.scan(self.db, self.lock, row, path, 17, row['info'], '')

    def test_same_manual_path_allowed_but_different_path_refused(self):
        self.update_scan(self.row(), self.path)
        self.assertEqual(self.row()['size'], 17)
        before = dict(self.row())
        with self.assertRaisesRegex(game_card_write.CardConflict, 'вручную'):
            self.update_scan(self.row(), self.other)
        self.assertEqual(dict(self.row()), before)
        self.assertFalse(self.db.in_transaction)

    def test_stale_info_or_path_cannot_replace_card(self):
        for operation in ('scan', 'metadata', 'settings'):
            with self.subTest(operation=operation):
                stale = self.row()
                new_info = dict(json.loads(stale['info']), note='changed elsewhere ' + operation)
                self.db.execute('update items set info=? where id=1', (json.dumps(new_info),)); self.db.commit()
                with self.assertRaisesRegex(game_card_write.CardConflict, 'изменилась'):
                    if operation == 'scan': self.update_scan(stale, self.path)
                    elif operation == 'metadata': game_card_write.metadata(self.db, self.lock, stale, 'Changed', '', '', stale['info'], '')
                    else: game_card_write.settings(self.db, self.lock, stale, stale['info'])
                self.assertEqual(json.loads(self.row()['info'])['note'], 'changed elsewhere ' + operation)
                self.assertFalse(self.db.in_transaction)

    def test_other_card_claims_path_between_lookup_and_scan(self):
        stale = self.row()
        self.db.execute("insert into items(id,title,kind,path,url,info) values(2,'Other','game',?,'game:other','{}')", (self.path,))
        self.db.commit()
        with self.assertRaisesRegex(game_card_write.CardConflict, 'другой карточкой'):
            self.update_scan(stale, self.path)
        with self.assertRaises(game_card_write.CardConflict):
            game_card_write.insert_scan(self.db, self.lock, 'New', 'Dev', self.path, 'new', 0, '', '', '{}')
        self.assertEqual(self.db.execute('select count(*) from items').fetchone()[0], 2)

    def test_bad_metadata_and_inconsistent_marker_are_not_overwritten(self):
        for info in ('bad json', '[]', json.dumps({'mediahub_manual_game_path_v1': self.other})):
            self.db.execute('update items set info=? where id=1', (info,)); self.db.commit()
            with self.assertRaises(game_card_write.CardConflict): self.update_scan(self.row(), self.path)
            self.assertEqual(self.row()['info'], info)

    def test_open_transaction_is_not_committed_or_rolled_back(self):
        row = self.row()
        self.db.execute("update items set title='uncommitted' where id=1")
        with self.assertRaises(game_card_write.CardConflict): self.update_scan(row, self.path)
        self.assertTrue(self.db.in_transaction)
        self.db.rollback(); self.assertEqual(self.row()['title'], 'Game')

    def test_trigger_failure_rolls_back(self):
        self.db.execute("create trigger deny_game before update on items begin select raise(abort,'denied'); end")
        self.db.commit(); before = dict(self.row())
        with self.assertRaises(sqlite3.IntegrityError): self.update_scan(self.row(), self.path)
        self.assertFalse(self.db.in_transaction); self.assertEqual(dict(self.row()), before)

    def test_settings_conflict_returns_409_without_losing_edit(self):
        stale = self.row()
        self.db.execute("update items set title='new title' where id=1"); self.db.commit()
        result, status = game_card_settings.save({'id': 1, 'note': 'mine'}, lambda _: stale,
            lambda row, info: game_card_write.settings(self.db, self.lock, row, info))
        self.assertEqual(status, 409, result)
        self.assertEqual(json.loads(self.row()['info'])['note'], 'keep')
        self.assertEqual(game_card_settings.save({'id': True}, lambda _: None, lambda *args: None)[1], 400)
