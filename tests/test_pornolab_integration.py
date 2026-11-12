"""Synthetic topic import, update and restart with no real site or extension."""
import os
import subprocess
import sys
import tempfile
import unittest


class PornolabIntegrationTests(unittest.TestCase):
    def test_inbox_import_update_conflict_and_restart(self):
        create = r'''
import base64
from pathlib import Path
from unittest.mock import patch
from legacy import app
PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/aN8AAAAASUVORK5CYII=')
def page(n, version='1.0', tags=True):
    return (f'<h1 class="maintitle">Example Game {n} [{version}] (Studio {n}) [uncen] '
            '[2026, SLG, Adventure] [eng+rus]</h1><div class="post_body">'
            + ('Теги: SLG, Adventure<br>' if tags else '') +
            f'<img class="postImg" src="https://images.example/tag.png">'
            f'<img class="postImg postImgAligned img-right" src="https://images.example/cover-{n}.png">'
            '</div>')
def fetch(url, job=None):
    n = int(url.split('t=')[1]); return page(n)
try:
    tabs = [{'id': n, 'url': f'https://pornolab.net/forum/viewtopic.php?t={n}&start=20',
             'title': f'Example {n}'} for n in (11, 12)]
    batch, count = app.inbox_add(tabs, False, 'test')
    rows = app.sql('select id,kind,action from inbox where batch=? order by id', (batch,))
    assert count == 2 and all(r['kind'] == 'unknown' and r['action'] == 'link' for r in rows)
    # Pornolab also has non-game topics, so the user explicitly selects the game action.
    result = app.inbox_confirm({'batch': batch, 'close': False, 'rows': [
        {'id': r['id'], 'kind': 'game', 'action': 'gamecard'} for r in rows]})
    assert result['download'] == 2
    with patch.object(app, 'ext_online', return_value=True), patch.object(app, 'fetch_html', side_effect=fetch), \
         patch.object(app.cover_download, 'download_cover', return_value=PNG) as covers:
        for _ in range(2):
            job = app.scheduler.pending.get_nowait(); app.scheduler.process(job)
            assert job['status'].startswith('готово'), job['status']
        assert [x.args[0] for x in covers.call_args_list] == [f'https://images.example/cover-{n}.png' for n in (11, 12)]
    app.settle()
    rows = app.sql("select * from items where kind='game' order by id")
    assert len(rows) == 2
    item = rows[0]; before = app.ginfo(item)['meta']
    assert item['title'] == 'Example Game 11' and before['version'] == '1.0'
    assert before['genres'] == ['SLG', 'Adventure'] and before['thread'].endswith('t=11')
    assert Path(item['thumb']).parent == app.BASE / 'covers'
    # Same source can update version; login page cannot overwrite any fields.
    with patch.object(app, 'ext_online', return_value=True), \
         patch.object(app, 'fetch_html', return_value=page(11, '1.1')):
        job = {'cancel': False, 'ids': [item['id']]}; app.game_check(job)
        assert 'проверено 1' in job['final'], job
    updated = app.sql('select * from items where id=?', (item['id'],))[0]
    assert app.ginfo(updated)['meta']['version'] == '1.1'
    prior = dict(updated)
    with patch.object(app, 'ext_online', return_value=True), \
         patch.object(app, 'fetch_html', return_value='<title>Login</title>'):
        job = {'cancel': False, 'ids': [item['id']]}; app.game_check(job)
        assert 'неизвестно/ошибка 1' in job['final'], job
    assert dict(app.sql('select * from items where id=?', (item['id'],))[0]) == prior
    # A different topic with the same title must not overwrite this card.
    other = dict(app.ginfo(updated)['meta'], version='9.0')
    try: app.apply_meta(other, 'https://pornolab.net/forum/viewtopic.php?t=999')
    except ValueError: pass
    else: raise AssertionError('similar card was silently overwritten')
    assert dict(app.sql('select * from items where id=?', (item['id'],))[0]) == prior
    with patch.object(app, 'ext_online', return_value=True), patch.object(app, 'fetch_html', return_value=page(15)), \
         patch.object(app.cover_download, 'download_cover', side_effect=OSError('offline')):
        job = {'id': 500, 'url': 'https://pornolab.net/forum/viewtopic.php?t=15', 'kind': 'gamecard',
               'cancel': False, 'status': '', 'speed': 0, 'pct': 0}
        app.scheduler.process(job)
        assert job['status'].startswith('частично:') and 'обложка недоступна' in job['status']
        assert app.sql("select * from items where src=?", (job['url'],))
finally: app.db.close()
'''
        restart = r'''
from pathlib import Path
from legacy import app
try:
    rows = app.sql("select * from items where kind='game' order by id")
    assert len(rows) == 3 and app.ginfo(rows[0])['meta']['version'] == '1.1'
    assert app.ginfo(rows[0])['meta']['genres'] == ['SLG', 'Adventure']
    assert Path(rows[0]['thumb']).is_file() and rows[0]['src'].endswith('t=11')
    assert len(app.sql("select id from inbox where status='done'")) == 2
finally: app.db.close()
'''
        with tempfile.TemporaryDirectory() as directory:
            env = dict(os.environ, MEDIAHUB_DATA_DIR=directory, MEDIAHUB_GAME_DELAY='0')
            for script in (create, restart):
                subprocess.run([sys.executable, '-c', script], env=env, check=True, timeout=40)


if __name__ == '__main__': unittest.main()
