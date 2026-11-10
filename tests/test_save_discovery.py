"""Read-only, bounded discovery of possible in-game save locations."""
from pathlib import Path
import os
import tempfile
import unittest
from unittest.mock import patch

from core.update_preview import preview_request
from legacy import gamesweep
from storage import save_discovery as saves


class SaveDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / 'games'
        self.game = self.root / 'Game v1'
        self.game.mkdir(parents=True)

    def scan(self):
        return saves.discover_saves(str(self.root), str(self.game))

    def test_finds_known_names_without_reading_or_writing(self):
        (self.game / 'wrapper' / 'saves').mkdir(parents=True)
        (self.game / 'wrapper' / 'saves' / 'slot').write_bytes(b'secret')
        (self.game / 'wrapper' / 'slot.rpgsave').write_bytes(b'data')
        (self.game / 'ignored.bin').write_bytes(b'ignored')
        before = {p.relative_to(self.game): p.read_bytes() for p in self.game.rglob('*') if p.is_file()}
        with patch('builtins.open', side_effect=AssertionError('must not open files')):
            result = self.scan()
        paths = {(c['path'].replace('\\', '/'), c['kind']) for c in result['candidates']}
        self.assertEqual(paths, {('wrapper/saves', 'directory'), ('wrapper/slot.rpgsave', 'file')})
        self.assertFalse(result['incomplete'])
        after = {p.relative_to(self.game): p.read_bytes() for p in self.game.rglob('*') if p.is_file()}
        self.assertEqual(before, after)

    def test_limits_and_busy(self):
        for n in range(4):
            (self.game / f'{n}.sav').write_bytes(b'x')
        for name, value in (('MAX_ENTRIES', 1), ('MAX_CANDIDATES', 1), ('MAX_SECONDS', -1)):
            with self.subTest(limit=name), patch.object(saves, name, value):
                result = self.scan()
                self.assertTrue(result['incomplete'])
                self.assertLessEqual(len(result['candidates']), 1)
        deep = self.game / 'wrapper'
        deep.mkdir()
        (deep / 'inner').mkdir()
        with patch.object(saves, 'MAX_DEPTH', 0):
            self.assertTrue(self.scan()['incomplete'])
        saves._LIMIT.acquire()
        try:
            with self.assertRaises(saves.DiscoveryBusy):
                self.scan()
        finally:
            saves._LIMIT.release()
        self.assertEqual(len(self.scan()['candidates']), 4)

    def test_outside_root_missing_files_and_symlinks(self):
        outside = Path(self.temp.name).resolve() / 'outside'
        outside.mkdir()
        (outside / 'secret.sav').write_bytes(b'other')
        for root, game in ((self.root, outside), (self.root, self.root), ('', self.game)):
            with self.subTest(root=root, game=game), self.assertRaises(ValueError):
                saves.discover_saves(str(root), str(game))
        link = self.game / 'linked'
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest('symlink creation requires privileges')
        result = self.scan()
        self.assertTrue(result['incomplete'])
        self.assertEqual(result['skipped'], 1)
        self.assertFalse(result['candidates'])
        with self.assertRaises(ValueError):
            saves.discover_saves(str(self.root), str(link))
        self.assertEqual((outside / 'secret.sav').read_bytes(), b'other')

    def test_failed_or_changed_subfolder_is_not_reported_as_complete(self):
        child = self.game / 'wrapper'
        child.mkdir()
        (child / 'slot.sav').write_bytes(b'old')
        real_scandir = saves.os.scandir
        def denied(path):
            if Path(path) == child:
                raise PermissionError('denied')
            return real_scandir(path)
        with patch.object(saves.os, 'scandir', side_effect=denied):
            result = self.scan()
        self.assertTrue(result['incomplete'])
        self.assertEqual(result['skipped'], 1)
        self.assertFalse(result['candidates'])

        class ChangingScan:
            def __init__(self, path):
                self.path = Path(path)
                self.iterator = real_scandir(path)
            def __enter__(self):
                return self.iterator.__enter__()
            def __exit__(self, *args):
                self.iterator.__exit__(*args)
                if self.path == self_game:
                    (child / 'new.sav').write_bytes(b'new')
                    info = child.stat()
                    os.utime(child, ns=(info.st_atime_ns, info.st_mtime_ns + 2_000_000_000))
        self_game = self.game
        with patch.object(saves.os, 'scandir', side_effect=ChangingScan):
            result = self.scan()
        self.assertTrue(result['incomplete'])
        self.assertFalse(result['candidates'])
        self.assertEqual((child / 'slot.sav').read_bytes(), b'old')

    def test_mode_rejects_client_paths_and_unknown_game(self):
        lookup = lambda item_id: {'path': str(self.game)} if item_id == 1 else None
        view = lambda game: game
        request = lambda data: preview_request(data, lookup, view, gamesweep.parse_name, '', str(self.root))
        self.assertEqual(request({'id': 1, 'mode': 'saves'})[0]['save_preview']['game_folder'], str(self.game))
        self.assertEqual(request({'id': 1, 'mode': 'saves', 'path': str(self.root)})[1], 400)
        self.assertEqual(request({'id': 1, 'mode': 'invalid'})[1], 400)
        self.assertEqual(request({'id': 2, 'mode': 'saves'})[1], 404)
        self.assertEqual(request({'id': True, 'mode': 'saves'})[1], 400)
