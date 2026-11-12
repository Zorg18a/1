"""Edge: find and explicitly associate a local game using temporary data only."""
import json
import os
from pathlib import Path
import tempfile
import threading
import traceback
from core.local_http import LocalHTTPServer as ThreadingHTTPServer


def run(root):
    from playwright.sync_api import expect, sync_playwright
    os.environ['MEDIAHUB_DATA_DIR'] = str(root)
    from legacy import app
    games = root / 'PG'
    folder = games / 'new7' / 'HiddenBadge_20260828c'
    (folder / 'saves').mkdir(parents=True)
    (folder / 'saves' / 'slot.sav').write_bytes(b'keep')
    extra = root / 'OtherDisk'
    other_folder = extra / 'HiddenBadge_20260828c'
    other_folder.mkdir(parents=True)
    (other_folder / 'data.txt').write_text('unchanged', encoding='utf-8')
    app.cfg['games_root'] = str(games)
    app.sql("insert into items(id,title,kind,path,url,info) values(1,'Hidden Badge','game','','game:hiddenbadge',?)",
            (json.dumps({'meta': {'thread': 'https://example.com/'}, 'note': 'keep'}),))
    app.sql("insert into items(id,title,kind,path,url,info) values(2,'Existing card','game',?,'game:existing','{}')", (str(folder),))
    server = ThreadingHTTPServer(('127.0.0.1', 0), app.H)
    thread = threading.Thread(target=server.serve_forever); thread.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel='msedge', headless=True)
            try:
                page = browser.new_page(viewport={'width': 320, 'height': 800})
                page.goto(f'http://127.0.0.1:{server.server_port}/', wait_until='domcontentloaded')
                page.get_by_role('navigation').get_by_role('link', name='Игры').click()
                card = page.locator('#ggrid .gcard')
                expect(card).to_have_count(2); card.filter(has_text='Hidden Badge').click()
                panel = page.locator('#gpanel')
                section = panel.locator('.local-game-search')
                section.get_by_label('Дополнительная папка для разового поиска', exact=False).fill(str(extra))
                section.get_by_role('button', name='Искать в дополнительной папке').click()
                expect(section).to_contain_text(str(other_folder))
                expect(section).to_contain_text('только просмотр, привязка недоступна')
                expect(section.get_by_role('button', name='Связать с карточкой:', exact=False)).to_have_count(0)
                assert app.sql('select path from items where id=1')[0]['path'] == ''
                assert (other_folder / 'data.txt').read_text('utf-8') == 'unchanged'
                section.get_by_role('button', name='Найти игру на диске').click()
                expect(section).to_contain_text('Путь уже связан с другой карточкой')
                expect(section).to_contain_text('Existing card')
                expect(section.get_by_role('button', name='Связать с карточкой:', exact=False)).to_have_count(0)
                section.get_by_role('button', name='Открыть карточку Existing card, ID 2').click()
                expect(panel).to_contain_text('Existing card')
                assert app.sql('select path from items where id=1')[0]['path'] == ''
                page.locator('#gclose').click()
                app.sql('delete from items where id=2')
                page.evaluate('loadGames()')
                expect(card).to_have_count(1); card.click()
                panel = page.locator('#gpanel')
                expect(panel).to_contain_text('Не скачано')
                section = panel.locator('.local-game-search')
                section.get_by_role('button', name='Найти игру на диске').click()
                expect(section).to_contain_text(str(folder))
                expect(section).to_contain_text('похожего на дату')
                choose = section.get_by_role('button', name='Связать с карточкой:', exact=False)
                page.once('dialog', lambda dialog: dialog.dismiss()); choose.click()
                assert app.sql('select path from items where id=1')[0]['path'] == ''
                page.once('dialog', lambda dialog: dialog.accept()); choose.click()
                expect(panel).to_contain_text('Скачано')
                expect(panel).to_contain_text(str(folder))
                expect(panel.locator('.local-game-search')).to_be_visible()
                expect(panel.locator('.game-tags-form')).to_be_visible()
                expect(panel.locator('.update-preview')).to_be_visible()
                assert app.sql('select path from items where id=1')[0]['path'] == str(folder)
                assert (folder / 'saves' / 'slot.sav').read_bytes() == b'keep'
                assert panel.evaluate('e => e.scrollWidth <= e.clientWidth + 1')
                print('Edge: explicit local game association passed')
            finally:
                browser.close()
    finally:
        server.shutdown(); server.server_close(); thread.join(); app.db.close()


if __name__ == '__main__':
    try:
        with tempfile.TemporaryDirectory() as directory:
            run(Path(directory).resolve())
    except Exception:
        if os.environ.get('GITHUB_ACTIONS'):
            text = traceback.format_exc()[-6000:].replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A')
            print(f'::error title=Local game Edge smoke failed::{text}', flush=True)
        raise
