"""Experiment: pin a created backup file without blocking SQLite writes."""
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest

from storage import guarded_read, windows_backup_pin


class PinPlatformTests(unittest.TestCase):
    @unittest.skipIf(os.name == 'nt', 'Windows NTFS is supported')
    def test_unsupported_platform_fails_closed(self):
        with self.assertRaises(guarded_read.GuardedReadUnsupported):
            windows_backup_pin.pin_created_file(None, 'file.partial', 0)


@unittest.skipUnless(os.name == 'nt', 'requires Windows NTFS')
class PinWindowsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()

    def create(self, name):
        path = self.root / name
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_BINARY, 0o600)
        return fd, path

    def test_sqlite_writes_and_no_replace_until_release(self):
        fd, partial = self.create('snapshot.partial')
        final = self.root / 'snapshot.db'
        try:
            with guarded_read.open_guarded_directory(str(self.root)) as directory:
                with windows_backup_pin.pin_created_file(directory, partial.name, fd):
                    os.close(fd); fd = None
                    with closing(sqlite3.connect(':memory:')) as source:
                        source.execute('create table demo(value)'); source.execute("insert into demo values('safe')"); source.commit()
                        with closing(sqlite3.connect(partial)) as target:
                            source.backup(target)
                            self.assertEqual(target.execute('pragma integrity_check').fetchone()[0], 'ok')
                    with self.assertRaises(OSError): partial.unlink()
                    with self.assertRaises(OSError): partial.rename(self.root / 'moved.partial')
                    with self.assertRaises(OSError): os.replace(partial, self.root / 'replaced.partial')
                    os.link(partial, final)
                    with closing(sqlite3.connect(final)) as result:
                        self.assertEqual(result.execute('select value from demo').fetchone()[0], 'safe')
                partial.unlink()
            self.assertTrue(final.is_file())
        finally:
            if fd is not None: os.close(fd)

    def test_mismatched_fd_and_hardlinks_fail_and_release_handle(self):
        fd, first = self.create('first.partial')
        second_fd, second = self.create('second.partial')
        try:
            with guarded_read.open_guarded_directory(str(self.root)) as directory:
                with self.assertRaises(guarded_read.GuardedReadError):
                    windows_backup_pin.pin_created_file(directory, second.name, fd)
                os.close(second_fd); second_fd = None
                second.rename(self.root / 'moved.partial')
                alias = self.root / 'alias.partial'
                os.link(first, alias)
                with self.assertRaises(guarded_read.GuardedReadError):
                    windows_backup_pin.pin_created_file(directory, first.name, fd)
            self.assertTrue(alias.is_file())
        finally:
            os.close(fd)
            if second_fd is not None: os.close(second_fd)

    def test_rejects_bad_names_and_closed_directory(self):
        fd, path = self.create('file.partial')
        try:
            directory = guarded_read.open_guarded_directory(str(self.root))
            with directory:
                for name in ('../file.partial', 'a/b', '', 'C:\\x', 'file.partial:stream'):
                    with self.subTest(name=name), self.assertRaises(guarded_read.GuardedReadError):
                        windows_backup_pin.pin_created_file(directory, name, fd)
                with self.assertRaises((OSError, ValueError)):
                    windows_backup_pin.pin_created_file(directory, path.name, 999999)
            with self.assertRaises(guarded_read.GuardedReadError):
                windows_backup_pin.pin_created_file(directory, path.name, fd)
        finally:
            os.close(fd)
