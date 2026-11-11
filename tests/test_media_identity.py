import os
from pathlib import Path
import tempfile
import unittest

from storage.media_identity import position_key


class MediaIdentityTests(unittest.TestCase):
    def test_identity_is_stable_and_detects_common_replacements(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'video.mp4'
            path.write_bytes(b'first')
            item = {'id': 1, 'kind': 'video', 'url': 'url:1', 'added': '2026-01-01', 'path': str(path)}
            first = position_key(item)
            self.assertEqual(len(first), 64)
            self.assertEqual(first, position_key(item))
            for name, value in [('id', 2), ('url', 'url:2'), ('added', 'later'), ('kind', 'audio')]:
                self.assertNotEqual(first, position_key(dict(item, **{name: value})))
            path.write_bytes(b'changed length')
            self.assertNotEqual(first, position_key(item))
            path.unlink()
            self.assertIsNone(position_key(item))
            self.assertIsNone(position_key(dict(item, path=directory)))
            self.assertIsNone(position_key(dict(item, path='relative.mp4')))
