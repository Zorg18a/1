"""Re-check the selected archive after scanning the game directory."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from core.update_inspect import inspect_request
from legacy import gamesweep
from storage.incoming_downloads import incoming_folder, list_archives
from storage.save_discovery import DiscoveryBusy


class SaveCompareRequestTests(unittest.TestCase):
    def test_archive_change_and_concurrent_scan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            downloads = root / 'downloads'; downloads.mkdir()
            games = root / 'games'; games.mkdir()
            game = games / 'Example Game v1'; game.mkdir()
            folder = incoming_folder(str(downloads), str(games))
            archive = folder / 'Example Game v2.zip'
            with zipfile.ZipFile(archive, 'w') as z:
                z.writestr('save.sav', b'new')
            entry = list_archives(folder)[0][0]
            payload = {'id': 1, 'name': entry['name'], 'identity': entry['identity'], 'compare_saves': True}
            lookup = lambda _: {'title': 'Example Game', 'path': str(game)}
            def request():
                return inspect_request(payload, lookup, gamesweep.parse_name, str(downloads), str(games))
            with patch('core.update_inspect.discover_saves', side_effect=DiscoveryBusy('busy')):
                self.assertEqual(request()[1], 409)
            def change(*args):
                with archive.open('ab') as output:
                    output.write(b'changed')
                return {'game_folder': str(game), 'incomplete': False, 'candidates': [], 'scanned': 0, 'skipped': 0}
            with patch('core.update_inspect.discover_saves', side_effect=change):
                self.assertEqual(request()[1], 409)
