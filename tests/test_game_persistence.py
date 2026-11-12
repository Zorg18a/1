"""Exercise 83 synthetic game tabs and library persistence across processes."""
import os
import subprocess
import sys
import tempfile
import unittest


class GamePersistenceTests(unittest.TestCase):
    def test_inbox_cards_and_video_survive_restart(self):
        first = r'''
import base64
from pathlib import Path
from unittest.mock import patch
from legacy import app
try:
    tabs = [{'id': i, 'url': f'https://f95zone.to/threads/game-{i}.{1000+i}/',
             'title': f'Example {i}'} for i in range(83)]
    batch, n = app.inbox_add(tabs, False, 'test')
    assert n == 83
    rows = app.sql('select id from inbox where batch=? order by id', (batch,))
    result = app.inbox_confirm({'batch': batch, 'close': False, 'rows': [
        {'id': row['id'], 'kind': 'game', 'action': 'gamecard'} for row in rows]})
    assert result['download'] == 83, result
    png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/aN8AAAAASUVORK5CYII=')
    def page(url, job):
        number = int(url.split('game-')[1].split('.')[0])
        return (f'<meta property="og:title" content="Unity - Example {number} [1.2] [Studio]">'
                '<meta property="og:image" content="/static/logo.png">'
                f'<div class="bbWrapper"><img src="https://images.example/poster-{number}.jpg">'
                'Genre: Adventure<br></div>')
    with patch.object(app, 'ext_online', return_value=True), patch.object(app, 'fetch_html', side_effect=page), \
         patch.object(app.cover_download, 'download_cover', return_value=png) as fetch:
        for _ in range(83): app.scheduler.process(app.scheduler.pending.get_nowait())
        assert fetch.call_count == 83
        assert all('poster-' in call.args[0] for call in fetch.call_args_list)
    app.settle()
    assert len(app.sql("select id from items where kind='game'")) == 83
    app.sql("insert into items(title,kind,path,url) values('Video','video','','https://example.org/video')")
finally:
    app.db.close()
'''
        second = r'''
from pathlib import Path
from legacy import app
try:
    games = app.sql("select * from items where kind='game' order by id")
    assert len(games) == 83
    for game in games:
        meta = app.ginfo(game)['meta']
        assert meta['version'] == '1.2' and 'Adventure' in meta['genres']
        assert 'poster-' in meta['cover'] and Path(game['thumb']).is_file()
        assert Path(game['thumb']).parent == Path(app.BASE) / 'covers'
        assert meta['thread'].startswith('https://f95zone.to/threads/')
    assert len(app.sql("select id from items where kind='video' and url='https://example.org/video'")) == 1
    assert len(app.sql("select id from inbox where status='done'")) == 83
finally:
    app.db.close()
'''
        with tempfile.TemporaryDirectory() as directory:
            env = dict(os.environ, MEDIAHUB_DATA_DIR=directory)
            for code in (first, second):
                subprocess.run([sys.executable, '-c', code], env=env, check=True, timeout=60)


if __name__ == '__main__': unittest.main()
