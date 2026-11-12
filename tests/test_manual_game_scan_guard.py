"""GameSweep must not replace a deliberately chosen path with a similar one."""
import os
import subprocess
import sys
import tempfile
import unittest


class ManualScanGuardTests(unittest.TestCase):
    def test_real_scan_surfaces_conflict_and_keeps_user_data(self):
        code = r'''
import json
from legacy import app
base = app.BASE; selected = base / 'selected'; other = base / 'other'
folder = selected / 'Hidden Badge'; (folder / 'saves').mkdir(parents=True)
(folder / 'saves' / 'slot.sav').write_bytes(b'keep')
conflict = other / 'Hidden Badge'; (conflict / 'saves').mkdir(parents=True)
(conflict / 'saves' / 'slot.sav').write_bytes(b'other')
app.cfg['folder'] = str(base / 'downloads'); app.cfg['games_root'] = str(selected)
info = {'note':'my note', 'meta':{'thread':'https://example.org/1'}}
app.sql("insert into items(id,title,kind,path,url,info) values(1,'Hidden Badge','game','','game:hiddenbadge',?)", (json.dumps(info),))
row = app.sql('select * from items where id=1')[0]
from core import local_game_match
res, status = local_game_match.find(row, str(selected), app.gamesweep.parse_name, app.db, app.lock)
assert status == 200 and len(res['candidates']) == 1
assert local_game_match.link({'id':1, 'token':res['candidates'][0]['token']}, app.db, app.lock, app.cfg)[1] == 200
before = dict(app.sql('select * from items where id=1')[0])
app.cfg['games_root'] = str(other)
store = app.gamesweep.Store(str(other)); store.running = True; store.on_done = app.sync_games
store._scan(str(other), 'auto')
assert 'Синхронизация библиотеки не завершена' in store.error, store.error
assert 'вручную выбранной связи' in store.error, store.error
assert dict(app.sql('select * from items where id=1')[0]) == before
assert (folder / 'saves' / 'slot.sav').read_bytes() == b'keep'
assert (conflict / 'saves' / 'slot.sav').read_bytes() == b'other'
assert len(app.sql("select * from items where kind='game'")) == 1
app.db.close()
'''
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run([sys.executable, '-c', code], env=dict(os.environ, MEDIAHUB_DATA_DIR=directory),
                           check=True, timeout=40)

    def test_link_during_metadata_update_is_not_overwritten(self):
        code = r'''
import json
from core import local_game_match
from storage.game_card_write import CardConflict
from legacy import app
root = app.BASE / 'games'; folder = root / 'Hidden Badge'; folder.mkdir(parents=True)
app.cfg['games_root'] = str(root)
app.sql("insert into items(id,title,kind,path,url,info) values(1,'Hidden Badge','game','','game:hiddenbadge',?)", (json.dumps({'note':'keep'}),))
row = app.sql('select * from items where id=1')[0]
res, status = local_game_match.find(row, str(root), app.gamesweep.parse_name, app.db, app.lock)
token = res['candidates'][0]['token']
def link_during_fetch(*args):
    assert local_game_match.link({'id':1, 'token':token}, app.db, app.lock, app.cfg)[1] == 200
    return ''
app.fetch_cover = link_during_fetch
try:
    app.apply_meta({'name':'Hidden Badge', 'version':'1', 'cover':'https://example.org/cover'}, 'https://example.org/thread')
    raise AssertionError('stale metadata accepted')
except CardConflict: pass
row = app.sql('select * from items where id=1')[0]; info = json.loads(row['info'])
assert row['path'] == str(folder) and info['mediahub_manual_game_path_v1'] == str(folder)
assert info['note'] == 'keep' and 'meta' not in info
app.db.close()
'''
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run([sys.executable, '-c', code], env=dict(os.environ, MEDIAHUB_DATA_DIR=directory),
                           check=True, timeout=40)
