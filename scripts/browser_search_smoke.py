"""Edge smoke for search and game matching, entirely on temporary local data."""
import json
import os
import struct
import zlib
from pathlib import Path
import tempfile
import threading
import traceback
from http.server import ThreadingHTTPServer


def test_png(width, height):
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    rows = (b'\0' + b'\xff\x80\x40' * width) * height
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)) +
            chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b''))


def run(root):
    from playwright.sync_api import expect, sync_playwright
    os.environ['MEDIAHUB_DATA_DIR'] = str(root)
    from legacy import app, gamesweep

    games_root = root / 'games'
    games_root.mkdir()
    for name in ('CollegeTraits v1.0', 'College Traits v1.1', 'College Traits 2 v1.0'):
        (games_root / name).mkdir()
    app.sql("insert into items(id,title,author,topic,kind,path,url,info) values(1,?,?,?,?,?,?,?)",
            ('CollegeTraits', '', '', 'game', '', 'game:collegetraits', json.dumps({'meta': {'genres': ['RPG'], 'developer': 'TestDev', 'engine': 'RenPy'}})))
    app.sql("insert into game_tags(item_id,position,tag) values(1,0,'Любимое')")
    app.sql("insert into items(id,title,author,topic,kind,path,url) values(2,?,?,?,?,?,?)",
            ('College Traits', '', '', 'video', '', 'video:college'))
    for item_id, dimensions in ((1, (12, 4)), (2, (4, 12))):
        cover = root / f'cover-{item_id}.png'
        cover.write_bytes(test_png(*dimensions))
        app.sql('update items set thumb=? where id=?', (str(cover), item_id))
    server = ThreadingHTTPServer(('127.0.0.1', 0), app.H)
    gs = gamesweep.make_server(str(games_root), 0)
    gs.store.games = gamesweep.scan_library(str(games_root))
    gs.store.rebuild(); gs.store.scanned = True
    threads = [threading.Thread(target=s.serve_forever) for s in (server, gs)]
    for thread in threads: thread.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel='msedge', headless=True)
            try:
                page = browser.new_page(viewport={'width': 1100, 'height': 800})
                page.goto(f'http://127.0.0.1:{server.server_port}/', wait_until='domcontentloaded')
                q = page.locator('#q')
                page.set_viewport_size({'width': 320, 'height': 800})
                expect(page.get_by_label('Поиск в библиотеке по названию, автору и теме')).to_be_visible()
                results = page.locator('#v-library .tools [aria-live="polite"]')
                expect(results).to_have_text('Показано материалов: 2')
                covers = page.locator('#lib .cv img')
                expect(covers).to_have_count(2)
                page.wait_for_function("[...document.querySelectorAll('#lib .cv img')].every(i => i.complete && i.naturalWidth > 0)")
                assert covers.evaluate_all("xs => xs.every(i => getComputedStyle(i).objectFit === 'contain')")
                page.locator('#so').select_option('size'); page.locator('#gb').select_option('topic')
                q.fill('College Traits')
                expect(results).to_have_text('Показано материалов: 2')
                page.locator('#chips button[onclick="setK(\'video\')"]').click()
                expect(results).to_have_text('Показано материалов: 1')
                reset = page.get_by_role('button', name='Сбросить поиск и тип')
                reset.focus(); page.keyboard.press('Enter')
                expect(q).to_be_focused(); expect(q).to_have_value('')
                expect(results).to_have_text('Показано материалов: 2')
                expect(page.locator('#chips button[onclick="setK(\'\')"]')).to_have_attribute('aria-pressed', 'true')
                expect(page.locator('#so')).to_have_value('size'); expect(page.locator('#gb')).to_have_value('topic')
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
                page.route('**/api/library?*', lambda route: route.abort())
                q.fill('offline')
                expect(results).to_contain_text('Не удалось обновить библиотеку')
                page.unroute('**/api/library?*')
                reset.click(); expect(results).to_have_text('Показано материалов: 2')
                page.set_viewport_size({'width': 1100, 'height': 800})
                for term in ('CollegeTraits', 'College Traits'):
                    q.fill('неттакойигры')
                    expect(page.locator('#lib')).to_contain_text('Ничего не нашлось')
                    q.fill(term)
                    expect(page.locator('#lib')).to_contain_text('CollegeTraits')
                    expect(page.locator('#lib')).to_contain_text('College Traits')
                page.get_by_role('navigation').get_by_role('link', name='Игры').click()
                gq = page.locator('#gq')
                page.set_viewport_size({'width': 320, 'height': 800})
                expect(page.get_by_label('Поиск игр по названию, разработчику, жанру, тегу или движку')).to_be_visible()
                game_results = page.locator('#gtab-lib .gtools [aria-live="polite"]')
                expect(game_results).to_have_text('Показано игр: 1 из 1')
                game_cover = page.locator('#ggrid .gart img')
                expect(game_cover).to_have_count(1)
                page.wait_for_function("document.querySelector('#ggrid .gart img')?.naturalWidth === 12")
                assert game_cover.evaluate("i => getComputedStyle(i).objectFit") == 'contain'
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
                page.locator('#gso').select_option('size')
                gq.fill('Любимое'); expect(game_results).to_have_text('Показано игр: 1 из 1')
                gq.fill('RenPy'); expect(game_results).to_have_text('Показано игр: 1 из 1')
                page.locator('#gens').click()
                page.locator('#genl [data-gen="любимое"]').click()
                expect(page.locator('#genl [data-gen="любимое"]')).to_have_attribute('aria-pressed', 'true')
                page.locator('#gens').click()
                page.locator('#gchips [data-gf="dl"]').focus(); page.keyboard.press('Enter')
                expect(page.locator('#gchips [data-gf="dl"]')).to_be_focused()
                expect(page.locator('#gchips [data-gf="dl"]')).to_have_attribute('aria-pressed', 'true')
                page.locator('#gsize').select_option('medium')
                expect(game_results).to_have_text('Показано игр: 0 из 1')
                game_reset = page.get_by_role('button', name='Сбросить поиск и фильтры игр')
                game_reset.focus(); page.keyboard.press('Enter')
                expect(gq).to_be_focused(); expect(gq).to_have_value('')
                expect(page.locator('#gsize')).to_have_value(''); expect(page.locator('#gso')).to_have_value('size')
                expect(page.locator('#gens')).to_have_text('Жанры и теги')
                expect(page.locator('#gchips [data-gf="all"]')).to_have_attribute('aria-pressed', 'true')
                expect(game_results).to_have_text('Показано игр: 1 из 1')
                assert page.evaluate("JSON.parse(localStorage.getItem('mediahub.game-view')).size") == ''
                assert app.sql('select tag from game_tags where item_id=1')[0]['tag'] == 'Любимое'
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
                page.route('**/api/library?*', lambda route: route.abort())
                page.get_by_role('button', name='Обновить список игр').click()
                expect(game_results).to_contain_text('Не удалось обновить игры')
                page.unroute('**/api/library?*')
                page.get_by_role('button', name='Обновить список игр').click()
                expect(game_results).to_have_text('Показано игр: 1 из 1')
                page.set_viewport_size({'width': 1100, 'height': 800})
                assert page.locator('#ggrid .gcard').first.evaluate('e => e.getBoundingClientRect().width >= 224')
                page.locator('#ggrid .gcard').first.click()
                expect(page.locator('#gpanel')).to_have_attribute('aria-hidden', 'false')
                assert page.locator('#gpanel .gmain img').evaluate("i => getComputedStyle(i).objectFit") == 'contain'
                page.locator('#gclose').click()
                for term in ('CollegeTraits', 'College Traits'):
                    gq.fill(term)
                    expect(page.locator('#ggrid')).to_contain_text('CollegeTraits')
                gq.fill('College Traits 2')
                expect(page.locator('#ggrid')).to_contain_text('Ничего не найдено')
                page.goto(f'http://127.0.0.1:{gs.server_address[1]}/?t={gs.token}', wait_until='domcontentloaded')
                expect(page.locator('#list')).to_contain_text('College Traits')
                for term in ('CollegeTraits', 'College Traits'):
                    page.locator('#q').fill('неттакойигры')
                    expect(page.locator('#count')).to_have_text('Групп: 0 из 1')
                    page.locator('#q').fill(term)
                    expect(page.locator('#count')).to_have_text('Групп: 1 из 1')
                page.locator('#q').fill('-CollegeTraits')
                expect(page.locator('#count')).to_have_text('Групп: 0 из 1')
                page.locator('[data-v="t"]').click()
                text = 'College Traits [v1.1] [Dev] – https://f95zone.to/threads/college-traits.12/'
                page.locator('#tfile').set_input_files({'name': 'tabs.txt', 'mimeType': 'text/plain', 'buffer': text.encode('utf8')})
                expect(page.locator('#tlist')).to_contain_text('College Traits')
                expect(page.locator('#tlist')).to_contain_text('College Traits v1.1')
                for term in ('CollegeTraits', 'College Traits'):
                    page.locator('#tq').fill('неттакойигры')
                    expect(page.locator('#tcount')).to_have_text('Показано 0 из 1')
                    page.locator('#tq').fill(term)
                    expect(page.locator('#tcount')).to_have_text('Показано 1 из 1')
                page.locator('#tq').fill('-CollegeTraits')
                expect(page.locator('#tcount')).to_have_text('Показано 0 из 1')
                print('Edge: library, games, versions and tabs joined/spaced search passed')
            finally:
                browser.close()
    finally:
        for s in (server, gs): s.shutdown(); s.server_close()
        for thread in threads: thread.join()
        app.db.close()


if __name__ == '__main__':
    try:
        with tempfile.TemporaryDirectory() as directory:
            run(Path(directory).resolve())
    except Exception:
        if os.environ.get('GITHUB_ACTIONS'):
            text = traceback.format_exc()[-6000:].replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A')
            print(f'::error title=Headless Edge search smoke failed::{text}', flush=True)
        raise
