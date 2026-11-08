import sqlite3
import tempfile
import unittest
from pathlib import Path

from core.game_tags import normalize_tags, save_tags_request
from storage.database import execute, open_database
from storage import game_tags


class GameTagTests(unittest.TestCase):
    def test_normalization_and_validation(self):
        self.assertEqual(normalize_tags(['  Visual   Novel ', 'visual novel', 'Романтика', 'романтика']),
                         ['Visual Novel', 'Романтика'])
        self.assertEqual(normalize_tags([]), [])
        for invalid in (None, 'tag', [3], [''], ['a,b'], ['a\nb'], ['x' * 41], ['x'] * 21):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                normalize_tags(invalid)
        for invalid_id in (None, '1', True, -1, 0):
            self.assertEqual(save_tags_request({'id': invalid_id, 'tags': []}, lambda *_: True)[1], 400)
        self.assertEqual(save_tags_request({'id': 1, 'tags': []}, lambda *_: False)[1], 404)

    def test_storage_persistence_rollback_and_deletion(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'library.db'
            db, lock = open_database(path)
            try:
                execute(db, lock, "insert into items(id,kind,title) values(1,'game','A'),(2,'video','B')")
                self.assertTrue(game_tags.replace_tags(db, lock, 1, ['First', 'Второй']))
                self.assertFalse(game_tags.replace_tags(db, lock, 2, ['No']))
                self.assertFalse(game_tags.replace_tags(db, lock, 999, ['No']))
                with self.assertRaises(sqlite3.IntegrityError):
                    game_tags.replace_tags(db, lock, 1, ['new', None])
                self.assertEqual(game_tags.all_tags(db, lock), {1: ['First', 'Второй']})
                db.close()
                db, lock = open_database(path)
                self.assertEqual(game_tags.all_tags(db, lock), {1: ['First', 'Второй']})
                self.assertTrue(game_tags.has_tags(db, lock, 1))
                execute(db, lock, 'delete from items where id=1')
                self.assertEqual(game_tags.all_tags(db, lock), {})
            finally:
                db.close()
