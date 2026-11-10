from pathlib import Path
import struct
import tempfile
import unittest
import warnings
import zipfile
from unittest.mock import patch

from core.zip_rules import ArchiveRejected
from storage.incoming_downloads import stat_identity
from storage.zip_inspection import ArchiveChanged, inspect_zip


def make_zip(path, names):
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', UserWarning)
        with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for name in names:
                archive.writestr(name, b'fixture')


def inspect(path):
    return inspect_zip(path, stat_identity(path.stat()))


class ZipInspectionTests(unittest.TestCase):
    def test_real_zip_and_unchanged_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'test.zip'
            make_zip(path, ['game/readme.txt', 'game/data.bin'])
            before = path.read_bytes()
            self.assertEqual(inspect(path), {'entries': 2, 'files': 2, 'uncompressed_bytes': 14})
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(list(Path(tmp).iterdir()), [path])

    def test_reject_invalid_structure_and_unsafe_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'test.zip'
            for names in (['../outside'], ['folder/file', 'FOLDER/file'], ['same', 'same']):
                make_zip(path, names)
                with self.subTest(names=names), self.assertRaises(ArchiveRejected):
                    inspect(path)
            make_zip(path, [])
            with self.assertRaises(ArchiveRejected):
                inspect(path)
            path.write_bytes(b'not zip')
            with self.assertRaises(ArchiveRejected):
                inspect(path)

    def test_detect_encryption_zip64_and_limits_in_actual_central_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'test.zip'
            make_zip(path, ['a', 'b'])
            original = path.read_bytes()
            cd = original.index(b'PK\x01\x02')
            for label, offset, fmt, value in [('encrypted', cd + 8, '<H', 1),
                                               ('zip64', cd + 20, '<I', 0xffffffff)]:
                altered = bytearray(original)
                struct.pack_into(fmt, altered, offset, value)
                path.write_bytes(altered)
                with self.subTest(label=label), self.assertRaises(ArchiveRejected):
                    inspect(path)
            path.write_bytes(original)
            with patch('storage.zip_inspection.MAX_ENTRIES', 1):
                with self.assertRaises(ArchiveRejected):
                    inspect(path)
            with patch('storage.zip_inspection.MAX_DIRECTORY_BYTES', 5):
                with self.assertRaises(ArchiveRejected):
                    inspect(path)

    def test_payload_crc_is_deliberately_not_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'test.zip'
            with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_STORED) as archive:
                archive.writestr('file.txt', b'original-data')
            data = path.read_bytes().replace(b'original-data', b'corrupt--data', 1)
            path.write_bytes(data)
            self.assertEqual(inspect(path)['files'], 1)
            with zipfile.ZipFile(path) as archive:
                with self.assertRaises(zipfile.BadZipFile):
                    archive.read('file.txt')

    def test_change_during_inspection_is_rejected(self):
        from storage import zip_inspection
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'test.zip'
            make_zip(path, ['a'])
            original = zip_inspection._read_directory
            def change(source, size):
                result = original(source, size)
                with path.open('ab') as output:
                    output.write(b'changed')
                return result
            with patch.object(zip_inspection, '_read_directory', side_effect=change):
                with self.assertRaises(ArchiveChanged):
                    inspect_zip(path, stat_identity(path.stat()))

    def test_stale_identity_missing_and_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'test.zip'
            make_zip(path, ['a'])
            before = stat_identity(path.stat())
            with path.open('ab') as output:
                output.write(b'changed')
            with self.assertRaises(ArchiveChanged):
                inspect_zip(path, before)
            with self.assertRaises(ArchiveChanged):
                inspect_zip(Path(tmp) / 'missing.zip', before)
            link = Path(tmp) / 'link.zip'
            try:
                link.symlink_to(path)
            except OSError:
                self.skipTest('symlink creation requires privileges')
            with self.assertRaises(ArchiveChanged):
                inspect_zip(link, stat_identity(link.lstat()))
