"""ZIP path listing is bounded, optional and does not extract or modify files."""
from pathlib import Path
import tempfile
import unittest
import zipfile

from core.update_inspect import inspect_request
from legacy import gamesweep
from storage.incoming_downloads import incoming_folder, list_archives


class ZipListingTests(unittest.TestCase):
    def test_bounded_listing_validation_and_stale_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            downloads = root / 'downloads'; downloads.mkdir()
            games = root / 'games'; games.mkdir()
            folder = incoming_folder(str(downloads), str(games))
            archive = folder / 'Example Game v2.zip'
            with zipfile.ZipFile(archive, 'w') as z:
                z.writestr('game/', b'')
                for i in range(205):
                    z.writestr(f'game/файл{i:03}.txt', b'data')
            before = archive.read_bytes()
            entry = list_archives(folder)[0][0]
            base = {'id': 1, 'name': entry['name'], 'identity': entry['identity']}
            def request(**options):
                return inspect_request({**base, **options}, lambda _: {'title': 'Example Game', 'path': ''},
                                       gamesweep.parse_name, str(downloads), str(games))
            result, status = request(list_names=True)
            self.assertEqual(status, 200)
            info = result['inspection']
            self.assertEqual((info['entries'], info['files']), (206, 205))
            self.assertEqual(len(info['paths']), 200)
            self.assertTrue(info['paths_truncated'])
            self.assertEqual(info['paths'][0], {'path': 'game/', 'kind': 'directory'})
            self.assertEqual(info['paths'][1], {'path': 'game/файл000.txt', 'kind': 'file'})
            self.assertNotIn('_entries', info)
            self.assertNotIn('paths', request()[0]['inspection'])
            for options in ({'list_names': 'true'}, {'list_names': True, 'verify_data': True},
                            {'list_names': True, 'compare_saves': True}, {'list_names': True, 'extra': 1}):
                self.assertEqual(request(**options)[1], 400)
            self.assertEqual(archive.read_bytes(), before)
            self.assertEqual(list(folder.iterdir()), [archive])
            with archive.open('ab') as stream: stream.write(b'x')
            self.assertEqual(request(list_names=True)[1], 409)

    def test_reject_unsafe_path_beyond_display_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); downloads = root / 'downloads'; downloads.mkdir()
            folder = incoming_folder(str(downloads), '')
            archive = folder / 'Example Game v2.zip'
            with zipfile.ZipFile(archive, 'w') as z:
                for i in range(200): z.writestr(f'file{i:03}', b'x')
                z.writestr('../outside', b'x')
            before = archive.read_bytes(); entry = list_archives(folder)[0][0]
            data = {'id': 1, 'name': entry['name'], 'identity': entry['identity'], 'list_names': True}
            result, status = inspect_request(data, lambda _: {'title': 'Example Game'}, gamesweep.parse_name,
                                             str(downloads), '')
            self.assertEqual(status, 422)
            self.assertIn('error', result)
            self.assertEqual(archive.read_bytes(), before)
            self.assertFalse((root / 'outside').exists())
