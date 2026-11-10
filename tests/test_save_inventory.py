"""Inventory uses only bounded metadata reads and never copies saves."""
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from storage import save_inventory as inventory
from storage.save_discovery import DiscoveryBusy


class SaveInventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / 'games'
        self.game = self.root / 'Game'
        (self.game / 'saves' / 'nested').mkdir(parents=True)
        (self.game / 'saves' / 'nested' / 'slot.bin').write_bytes(b'secret')
        (self.game / 'other.sav').write_bytes(b'save')
        (self.game / 'ignored.txt').write_bytes(b'not a save')

    def scan(self):
        return inventory.inventory_saves(str(self.root), str(self.game))

    def test_nested_files_sizes_and_non_destructive(self):
        before = {p.relative_to(self.game): p.read_bytes() for p in self.game.rglob('*') if p.is_file()}
        with patch('builtins.open', side_effect=AssertionError('file contents must not be read')), \
             patch.object(Path, 'open', side_effect=AssertionError('file contents must not be read')):
            result = self.scan()
        files = {f['path'].replace('\\', '/'): f['size_bytes'] for f in result['files']}
        self.assertEqual(files, {'other.sav': '4', 'saves/nested/slot.bin': '6'})
        self.assertEqual(result['total_bytes'], '10')
        self.assertEqual(result['locations'], 2)
        self.assertFalse(result['incomplete'])
        after = {p.relative_to(self.game): p.read_bytes() for p in self.game.rglob('*') if p.is_file()}
        self.assertEqual(before, after)

    def test_limits_and_concurrent_requests(self):
        for name, value in (('MAX_FILES', 1), ('MAX_ENTRIES', 1), ('MAX_SECONDS', -1),
                            ('MAX_PATH_BYTES', 1), ('MAX_DEPTH', 0)):
            with self.subTest(limit=name), patch.object(inventory, name, value):
                result = self.scan()
                self.assertTrue(result['incomplete'])
                if name == 'MAX_ENTRIES':
                    self.assertLessEqual(result['scanned'], 1)
        inventory._LIMIT.acquire()
        try:
            with self.assertRaises(DiscoveryBusy):
                self.scan()
        finally:
            inventory._LIMIT.release()
        self.assertFalse(self.scan()['incomplete'])

    def test_unreadable_and_changed_directory_mark_incomplete(self):
        target = self.game / 'saves' / 'nested'
        real_scandir = inventory.os.scandir
        def denied(path):
            if Path(path) == target:
                raise PermissionError('denied')
            return real_scandir(path)
        with patch.object(inventory.os, 'scandir', side_effect=denied):
            result = self.scan()
        self.assertTrue(result['incomplete'])
        self.assertGreater(result['skipped'], 0)
        self.assertNotIn('slot.bin', [Path(f['path']).name for f in result['files']])
        class ChangingScan:
            def __init__(self, path):
                self.path = Path(path); self.iterator = real_scandir(path)
            def __enter__(self):
                return self.iterator.__enter__()
            def __exit__(self, *args):
                self.iterator.__exit__(*args)
                if self.path == target:
                    (target / 'new.bin').write_bytes(b'new')
                    st = target.stat()
                    os.utime(target, ns=(st.st_atime_ns, st.st_mtime_ns + 2_000_000_000))
        with patch.object(inventory.os, 'scandir', side_effect=ChangingScan):
            result = self.scan()
        self.assertTrue(result['incomplete'])
        self.assertEqual((target / 'slot.bin').read_bytes(), b'secret')

    def test_reparse_points_not_treated_as_regular_files_or_directories(self):
        import stat
        file = SimpleNamespace(st_mode=stat.S_IFREG, st_file_attributes=0x400)
        directory = SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)
        self.assertFalse(inventory._regular(file))
        self.assertFalse(inventory._directory(directory))

    def test_candidate_changed_between_search_and_inventory(self):
        real_inventory = inventory._inventory
        def change(root, game, preview):
            path = self.game / 'other.sav'
            path.write_bytes(b'changed-content')
            return real_inventory(root, game, preview)
        with patch.object(inventory, '_inventory', side_effect=change):
            result = self.scan()
        self.assertTrue(result['incomplete'])
        self.assertNotIn('other.sav', [Path(f['path']).name for f in result['files']])
        self.assertEqual((self.game / 'other.sav').read_bytes(), b'changed-content')

    def test_symlinks_are_skipped(self):
        outside = Path(self.temp.name).resolve() / 'outside'
        outside.mkdir(); (outside / 'secret.bin').write_bytes(b'outside')
        try:
            (self.game / 'saves' / 'link').symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest('symlink creation requires privileges')
        result = self.scan()
        self.assertTrue(result['incomplete'])
        self.assertGreater(result['skipped'], 0)
        self.assertNotIn('secret.bin', [Path(f['path']).name for f in result['files']])
        self.assertEqual((outside / 'secret.bin').read_bytes(), b'outside')
