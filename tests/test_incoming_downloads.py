import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.update_preview import archive_stem, preview_request
from legacy import gamesweep
from storage import incoming_downloads


class IncomingDownloadTests(unittest.TestCase):
    def test_folder_and_overlap_restrictions(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / 'media'
            base.mkdir()
            root = Path(tmp) / 'games'
            root.mkdir()
            folder = incoming_downloads.incoming_folder(str(base), str(root))
            self.assertEqual(folder, (base / 'Incoming_Downloads').resolve())
            self.assertTrue(folder.is_dir())
            for games in (base, folder, folder / 'nested'):
                with self.subTest(games=games), self.assertRaises(ValueError):
                    incoming_downloads.incoming_folder(str(base), str(games))
            with self.assertRaises(ValueError):
                incoming_downloads.incoming_folder('', '')
            with self.assertRaises(ValueError):
                incoming_downloads.incoming_folder(str(base / 'not-here'), '')

    def test_symlink_folder_and_archive_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            base, other = Path(tmp) / 'base', Path(tmp) / 'other'
            base.mkdir(); other.mkdir()
            link = base / 'Incoming_Downloads'
            try:
                link.symlink_to(other, target_is_directory=True)
            except OSError:
                self.skipTest('symlink creation requires privileges')
            with self.assertRaises(ValueError):
                incoming_downloads.incoming_folder(str(base))
            (other / 'real.zip').write_bytes(b'zip data')
            try:
                (other / 'link.zip').symlink_to(other / 'real.zip')
            except OSError:
                self.skipTest('symlink creation requires privileges')
            entries, truncated = incoming_downloads.list_archives(other)
            self.assertFalse(truncated)
            self.assertEqual([e['name'] for e in entries], ['real.zip'])

    def test_listing_is_bounded_and_game_sweep_ignores_incoming(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / 'Incoming_Downloads'
            folder.mkdir()
            (folder / 'a.zip').write_bytes(b'1')
            (folder / 'b.rar').write_bytes(b'22')
            (folder / 'c.zip.part').write_bytes(b'partial')
            with patch.object(incoming_downloads, 'SCAN_LIMIT', 1):
                entries, truncated = incoming_downloads.list_archives(folder)
            self.assertTrue(truncated)
            self.assertLessEqual(len(entries), 1)
            self.assertFalse(gamesweep.list_games(tmp))
            self.assertEqual((folder / 'a.zip').read_bytes(), b'1')

    def test_matching_is_exact_and_preview_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = incoming_downloads.incoming_folder(tmp)
            for name in ('Game v1.2.zip', 'Game v1.3.tar.gz', 'Game 2 v1.2.zip', 'Game v1.2.zip.part'):
                (folder / name).write_bytes(b'not an actual archive')
            game = {'title': 'Game'}
            view = lambda _: {'path': 'installed', 'version': '1.0', 'latest': '1.3'}
            find = lambda ident: game if ident == 1 else None
            args = (find, view, gamesweep.parse_name, tmp, '')
            result, status = preview_request({'id': 1}, *args)
            self.assertEqual(status, 200)
            self.assertEqual({x['name'] for x in result['candidates']}, {'Game v1.2.zip', 'Game v1.3.tar.gz'})
            self.assertEqual({x['version'] for x in result['candidates']}, {'1.2', '1.3'})
            self.assertEqual(result['installed_path'], 'installed')
            self.assertEqual(archive_stem('Game.tar.gz'), 'Game')
            for invalid in (True, '1', 0, None):
                self.assertEqual(preview_request({'id': invalid}, *args)[1], 400)
            self.assertEqual(preview_request({'id': 2}, *args)[1], 404)
            self.assertTrue(all(p.read_bytes() == b'not an actual archive' for p in folder.iterdir()))
            many = [{'name': f'Game v1.2 ({i}).zip', 'size': i, 'mtime': i} for i in range(60)]
            with patch('core.update_preview.list_archives', return_value=(many, False)):
                limited, status = preview_request({'id': 1}, *args)
            self.assertEqual(status, 200)
            self.assertEqual(len(limited['candidates']), 50)
            self.assertTrue(limited['truncated'])
