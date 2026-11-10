"""Windows NTFS handle guard, exercised only on temporary fixtures."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from storage.guarded_read import GuardedReadError, GuardedReadUnsupported, _relative_parts, open_guarded_file


class GuardedPathValidationTests(unittest.TestCase):
    def test_relative_paths_reject_ambiguous_windows_names(self):
        self.assertEqual(_relative_parts('saves/slot.sav'), ['saves', 'slot.sav'])
        for path in ('', '../secret', 'a/../b', 'C:\\secret', '\\\\server\\share',
                     'a//b', 'a:stream', 'a/b.', 'a/b ', 'a/\x00b'):
            with self.subTest(path=path), self.assertRaises(GuardedReadError):
                _relative_parts(path)

    @unittest.skipIf(os.name == 'nt', 'Windows supports the guarded reader')
    def test_non_windows_fails_closed(self):
        with self.assertRaises(GuardedReadUnsupported):
            open_guarded_file('/tmp', 'save.sav')


@unittest.skipUnless(os.name == 'nt', 'requires Windows NTFS handle semantics')
class GuardedWindowsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.game = self.base / 'Game'
        (self.game / 'saves').mkdir(parents=True)
        self.file = self.game / 'saves' / 'slot.sav'
        self.file.write_bytes(b'original')

    def open(self):
        return open_guarded_file(str(self.game), 'saves/slot.sav')

    def test_guards_file_and_ancestors_then_releases_handles(self):
        with self.open() as source:
            self.assertEqual(source.read(3), b'ori')
            self.assertEqual(source.read(), b'ginal')
            with self.assertRaises(GuardedReadError):
                source.read(-1)
            with self.assertRaises(GuardedReadError):
                source.read(1024 * 1024 + 1)
            with self.assertRaises(OSError):
                self.file.rename(self.file.with_name('moved.sav'))
            with self.assertRaises(OSError):
                (self.game / 'saves').rename(self.game / 'moved')
            with self.assertRaises(OSError):
                self.game.rename(self.base / 'moved-game')
            with self.assertRaises(OSError):
                self.file.open('wb')
        self.assertEqual(self.file.read_bytes(), b'original')
        moved = self.file.with_name('moved.sav')
        self.file.rename(moved)
        self.assertEqual(moved.read_bytes(), b'original')

    def test_rejects_active_writer_hardlink_and_missing_path(self):
        with self.file.open('r+b'):
            with self.assertRaises(OSError):
                self.open()
        alias = self.game / 'saves' / 'alias.sav'
        try:
            os.link(self.file, alias)
        except OSError:
            self.skipTest('hard links unavailable')
        with self.assertRaises(GuardedReadError):
            self.open()
        self.assertEqual(self.file.read_bytes(), b'original')
        with self.assertRaises(OSError):
            open_guarded_file(str(self.game), 'saves/missing.sav')

    def test_directory_junction_is_rejected_without_following(self):
        outside = self.base / 'outside'
        outside.mkdir(); (outside / 'secret.sav').write_bytes(b'outside')
        junction = self.game / 'junction'
        proc = subprocess.run(['cmd', '/c', 'mklink', '/J', str(junction), str(outside)],
                              capture_output=True, text=True)
        if proc.returncode:
            self.skipTest('junction creation unavailable: ' + proc.stderr)
        try:
            with self.assertRaises(GuardedReadError):
                open_guarded_file(str(self.game), 'junction/secret.sav')
            with self.assertRaises(GuardedReadError):
                open_guarded_file(str(junction), 'secret.sav')
            self.assertEqual((outside / 'secret.sav').read_bytes(), b'outside')
        finally:
            os.rmdir(junction)

    def test_non_local_or_relative_root_is_rejected(self):
        for root in ('relative', r'\\server\share', r'\\?\C:\Games', str(self.game / '..' / 'Game')):
            with self.subTest(root=root), self.assertRaises(GuardedReadError):
                open_guarded_file(root, 'saves/slot.sav')
