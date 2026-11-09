import stat
import unittest
import zipfile
from unittest.mock import patch

from core import zip_rules


def entry(name, *, directory=False):
    item = zipfile.ZipInfo(name + ('/' if directory and not name.endswith('/') else ''))
    item.file_size = 5 if not directory else 0
    item.compress_size = item.file_size
    return item


class ZipRulesTests(unittest.TestCase):
    def test_valid_tree_and_implicit_directories(self):
        result = zip_rules.check_zip_entries([entry('game/save/file.sav'), entry('game', directory=True), entry('game/readme.txt')])
        self.assertEqual(result, {'entries': 3, 'files': 2, 'uncompressed_bytes': 10})

    def test_reject_unsafe_names(self):
        names = ['/absolute', '../escape', 'a/../b', 'a//b', 'a/./b', r'C:\\evil',
                 'dir\\evil', 'x:stream', 'NUL.txt', 'com1.dat', 'Lpt².log',
                 'a./b', 'a /b', 'a/evil?.txt', 'bad\x00name', 'a/\ud800']
        for name in names:
            with self.subTest(name=repr(name)), self.assertRaises(zip_rules.ArchiveRejected):
                zip_rules.check_zip_entries([entry(name)])

    def test_collisions_and_file_directory_conflicts(self):
        cases = [('game/x', 'game/x'), ('Game/a', 'game/b'), ('café', 'cafe\u0301'),
                 ('dir', 'dir/file'), ('dir/file', 'DIR/file')]
        for pair in cases:
            with self.subTest(pair=pair), self.assertRaises(zip_rules.ArchiveRejected):
                zip_rules.check_zip_entries([entry(pair[0]), entry(pair[1])])

    def test_reject_special_files_encryption_and_compression(self):
        link = entry('shortcut'); link.create_system = 3; link.external_attr = (stat.S_IFLNK | 0o777) << 16
        device = entry('device'); device.create_system = 3; device.external_attr = (stat.S_IFCHR | 0o600) << 16
        encrypted = entry('secret'); encrypted.flag_bits = 1
        strong_encryption = entry('strong'); strong_encryption.flag_bits = 0x40
        unsupported = entry('file'); unsupported.compress_type = zipfile.ZIP_BZIP2
        wrong_kind = entry('folder/'); wrong_kind.create_system = 3; wrong_kind.external_attr = (stat.S_IFREG | 0o644) << 16
        for item in (link, device, encrypted, strong_encryption, unsupported, wrong_kind):
            with self.subTest(name=item.filename), self.assertRaises(zip_rules.ArchiveRejected):
                zip_rules.check_zip_entries([item])

    def test_limits(self):
        with patch.object(zip_rules, 'MAX_ENTRIES', 1):
            with self.assertRaises(zip_rules.ArchiveRejected):
                zip_rules.check_zip_entries([entry('a'), entry('b')])
        large = entry('big'); large.file_size = zip_rules.MAX_ENTRY_SIZE + 1
        with self.assertRaises(zip_rules.ArchiveRejected):
            zip_rules.check_zip_entries([large])
        compressed = entry('bomb'); compressed.file_size = 11 * 1024 ** 2; compressed.compress_size = 1
        with self.assertRaises(zip_rules.ArchiveRejected):
            zip_rules.check_zip_entries([compressed])
        zero = entry('zero'); zero.compress_size = 0
        with self.assertRaises(zip_rules.ArchiveRejected):
            zip_rules.check_zip_entries([zero])
        with patch.object(zip_rules, 'MAX_TOTAL_SIZE', 9):
            with self.assertRaises(zip_rules.ArchiveRejected):
                zip_rules.check_zip_entries([entry('a'), entry('b')])
