"""Only the validated manual extra-root marker may extend save discovery."""
import json
from pathlib import Path
import tempfile
import unittest

from core.save_preview import save_preview_request
from storage.game_save_root import save_root
from storage.save_discovery import discover_saves


class GameSaveRootTests(unittest.TestCase):
    def test_saved_extra_root_and_corrupt_markers_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve(); main = base / 'main'; main.mkdir()
            extra = base / 'extra'; game = extra / 'Game'; (game / 'saves').mkdir(parents=True)
            (game / 'saves' / 'slot.sav').write_bytes(b'preserved')
            info = {'mediahub_extra_game_root_v1': str(extra), 'mediahub_manual_game_path_v1': str(game), 'inst': {'path': str(game)}}
            row = {'path': str(game), 'info': json.dumps(info)}
            self.assertEqual(save_root(row, str(main)), str(extra))
            view = lambda r: {'path': r['path']}
            for mode in ('saves', 'save_inventory'):
                data, status = save_preview_request({'id':1, 'mode':mode}, row, view, str(main))
                self.assertEqual(status, 200, data)
            for changed in ({**info, 'mediahub_manual_game_path_v1': str(main)},
                            {**info, 'mediahub_extra_game_root_v1': 'relative'},
                            {**info, 'inst': {'path': str(main)}},
                            {**info, 'mediahub_extra_game_root_v1': str(main)}):
                row['info'] = json.dumps(changed)
                self.assertEqual(save_preview_request({'id':1,'mode':'saves'}, row, view, str(main))[1], 400)
            row['info'] = json.dumps({**info, 'mediahub_manual_game_path_v1': None})
            self.assertEqual(save_preview_request({'id':1,'mode':'saves'}, row, view, str(main))[1], 400)
            row['info'] = 'broken'
            self.assertEqual(save_preview_request({'id':1,'mode':'saves'}, row, view, str(main))[1], 400)
            self.assertEqual((game / 'saves' / 'slot.sav').read_bytes(), b'preserved')
            self.assertEqual(save_root({'path': str(game)}, str(main)), str(main))
            with self.assertRaises(ValueError): discover_saves(str(main), str(game))
