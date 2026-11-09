"""Content verification remains read-only and bounded."""
import io
from pathlib import Path
import struct
import tempfile
import unittest
import zipfile
from unittest.mock import patch

from core.zip_rules import ArchiveRejected
from storage.incoming_downloads import stat_identity
from storage.zip_content import VerificationBusy, _LIMIT
from storage.zip_inspection import ArchiveChanged, inspect_zip


class NonSeekable(io.BytesIO):
    def seekable(self):
        return False

    def seek(self, *args):
        raise io.UnsupportedOperation()


def create(method=zipfile.ZIP_DEFLATED, descriptor=False):
    data = NonSeekable() if descriptor else io.BytesIO()
    with zipfile.ZipFile(data, 'w', compression=method) as archive:
        archive.writestr('game/file.txt', b'hello world' * 10000)
        archive.writestr('game/empty', b'')
    return data.getvalue()


class ZipContentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'archive.zip'

    def verify(self, data):
        self.path.write_bytes(data)
        identity = stat_identity(self.path.stat())
        result = inspect_zip(self.path, identity, verify_data=True)
        self.assertEqual(self.path.read_bytes(), data)
        self.assertEqual(list(Path(self.tmp.name).iterdir()), [self.path])
        return result

    def test_stored_deflated_and_descriptor(self):
        for method in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
            for descriptor in (False, True):
                with self.subTest(method=method, descriptor=descriptor):
                    result = self.verify(create(method, descriptor))
                    self.assertEqual(result['verified_files'], 2)
                    self.assertEqual(result['verified_bytes'], 110000)

    def test_corrupt_payload_crc_header_and_descriptor(self):
        original = create(zipfile.ZIP_STORED)
        cd = original.index(b'PK\x01\x02')
        for offset in (30, 14, 4, 10, 30 + len('game/file.txt'), cd + 16):
            data = bytearray(original)
            data[offset] ^= 1
            with self.subTest(offset=offset), self.assertRaises(ArchiveRejected):
                self.verify(data)
        data = bytearray(create(descriptor=True))
        pos = data.index(b'PK\x07\x08')
        data[pos + 4] ^= 1
        with self.assertRaises(ArchiveRejected):
            self.verify(data)
        data = bytearray(create())
        data[30 + len('game/file.txt')] ^= 0xff
        with self.assertRaises(ArchiveRejected):
            self.verify(data)

    def test_declared_size_offset_and_limits(self):
        original = create()
        cd = original.index(b'PK\x01\x02')
        for offset, value in ((cd + 20, 1), (cd + 24, 1), (cd + 42, 1)):
            data = bytearray(original)
            struct.pack_into('<I', data, offset, value)
            with self.subTest(offset=offset), self.assertRaises(ArchiveRejected):
                self.verify(data)
        data = bytearray(original)
        struct.pack_into('<I', data, 22, 1)
        struct.pack_into('<I', data, cd + 24, 1)
        with self.assertRaises(ArchiveRejected):
            self.verify(data)
        data = bytearray(original)
        second = data.index(b'PK\x01\x02', cd + 4)
        struct.pack_into('<I', data, second + 42, 0)
        with self.assertRaises(ArchiveRejected):
            self.verify(data)
        for constant in ('MAX_COMPRESSED', 'MAX_UNCOMPRESSED', 'MAX_LOCAL_METADATA', 'MAX_SECONDS'):
            with self.subTest(constant=constant), patch('storage.zip_content.' + constant, -1):
                with self.assertRaises(ArchiveRejected):
                    self.verify(original)
        _LIMIT.acquire()
        try:
            with self.assertRaises(VerificationBusy):
                self.verify(original)
        finally:
            _LIMIT.release()
        self.assertEqual(self.verify(original)['verified_files'], 2)

    def test_changed_during_verification(self):
        from storage import zip_inspection
        data = create()
        self.path.write_bytes(data)
        identity = stat_identity(self.path.stat())
        real = zip_inspection.verify_content
        def modify(source, entries, offset):
            result = real(source, entries, offset)
            with self.path.open('ab') as output:
                output.write(b'changed')
            return result
        with patch.object(zip_inspection, 'verify_content', side_effect=modify):
            with self.assertRaises(ArchiveChanged):
                inspect_zip(self.path, identity, verify_data=True)
