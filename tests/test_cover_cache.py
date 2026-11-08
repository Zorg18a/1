import base64
import tempfile
import unittest
from pathlib import Path

from storage.cover_cache import MAX_COVER_BYTES, cache_bytes, cache_local_cover, image_extension

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/aN8AAAAASUVORK5CYII=')


class CoverCacheTests(unittest.TestCase):
    def test_supported_signatures_and_rejections(self):
        self.assertEqual(image_extension(PNG), 'png')
        self.assertEqual(image_extension(b'\xff\xd8\xffrest'), 'jpg')
        self.assertEqual(image_extension(b'RIFF1234WEBP'), 'webp')
        self.assertEqual(image_extension(b'GIF89a'), 'gif')
        self.assertEqual(image_extension(b'0000ftypavif'), 'avif')
        for value in (b'', b'<svg/>', b'<html>'):
            self.assertIsNone(image_extension(value))
        with tempfile.TemporaryDirectory() as temp:
            for value in (b'<svg/>', PNG + b'x' * MAX_COVER_BYTES):
                with self.assertRaises(ValueError):
                    cache_bytes(value, temp)
            self.assertFalse((Path(temp) / 'covers').exists())
            with self.assertRaises(ValueError):
                cache_bytes(PNG, '')

    def test_only_known_root_names_and_non_destructive_cache(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            game = root / 'game'
            game.mkdir()
            (game / 'cover.jpg').write_bytes(b'not an image')
            (game / 'Folder.PNG').write_bytes(PNG)
            (game / 'other.png').write_bytes(PNG)
            (game / 'nested').mkdir()
            (game / 'nested' / 'cover.png').write_bytes(PNG)
            first = Path(cache_local_cover(game, root / 'MediaHub'))
            second = Path(cache_local_cover(game, root / 'MediaHub'))
            self.assertNotEqual(first, second)
            self.assertEqual(first.parent, root / 'MediaHub' / 'covers')
            self.assertEqual(first.read_bytes(), PNG)
            self.assertEqual(second.read_bytes(), PNG)
            self.assertEqual((game / 'Folder.PNG').read_bytes(), PNG)
            self.assertEqual((game / 'cover.jpg').read_bytes(), b'not an image')
            self.assertEqual(cache_local_cover(root / 'archive.zip', root), '')
            self.assertEqual(cache_local_cover(game / 'nested' / 'cover.png', root), '')

    def test_local_symlinks_are_not_followed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'outside.png'
            source.write_bytes(PNG)
            game = root / 'game'
            game.mkdir()
            try:
                (game / 'cover.png').symlink_to(source)
                (root / 'linked-game').symlink_to(game, target_is_directory=True)
            except OSError:
                self.skipTest('symlink creation requires privileges')
            self.assertEqual(cache_local_cover(game, root), '')
            self.assertEqual(cache_local_cover(root / 'linked-game', root), '')
            self.assertEqual(source.read_bytes(), PNG)
