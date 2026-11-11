"""Recent metadata uses current records and never returns local paths."""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from core import recent_items, ui_assets
from storage import recent_items as metadata, reader_snapshot


class RecentTests(unittest.TestCase):
    def test_metadata_identities_and_missing_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            media = root / 'song.wav'
            media.write_bytes(b'abc')
            item = dict(id=1, title='<b>title</b>', kind='audio', path=str(media), url='a', root='', added='today')
            first = metadata.describe(item)
            self.assertEqual(first['title'], '<b>title</b>')
            self.assertNotIn(str(root), json.dumps(first))
            item['title'] = 'Renamed'
            self.assertEqual(first['identity'], metadata.describe(item)['identity'])
            media.write_bytes(b'changed')
            self.assertNotEqual(first['identity'], metadata.describe(item)['identity'])
            media.unlink()
            self.assertIsNone(metadata.describe(item))
            item.update(kind='manga', root=str(root), url='manga:test')
            self.assertIsNone(metadata.describe(item))
            (root / 'manifest.json').write_text('{}', encoding='utf8')
            first = metadata.describe(item)
            self.assertEqual(first['live_identity'], reader_snapshot.view_identity(1, 'manga:test', str(root)))
            item['url'] = 'manga:other'
            self.assertNotEqual(first['identity'], metadata.describe(item)['identity'])
            self.assertNotEqual(first['live_identity'], metadata.describe(item)['live_identity'])
            item['root'] = 'relative'
            self.assertIsNone(metadata.describe(item))
            item['kind'] = 'game'
            self.assertIsNone(metadata.describe(item))

    def test_route_validates_id_and_errors(self):
        class Handler:
            def js(self, obj, status=200): return status, obj
        h = Handler()
        for path in ('/api/recent/-1', '/api/recent/0', '/api/recent/9223372036854775808', '/api/recent/1/extra'):
            self.assertEqual(recent_items.get(h, path, lambda *_: self.fail('query')), (404, {'error': 'Материал не найден'}))
        self.assertEqual(recent_items.get(h, '/api/recent/1', lambda *_: [])[0], 404)
        def fail(*_): raise sqlite3.OperationalError('private')
        status, data = recent_items.get(h, '/api/recent/1', fail)
        self.assertEqual(status, 500)
        self.assertNotIn('private', data['error'])
        self.assertTrue(ui_assets.allowed('/ui/recent.js'))
        self.assertFalse(ui_assets.allowed('/ui/../storage/recent_items.py'))
