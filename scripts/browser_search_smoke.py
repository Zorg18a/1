"""Edge smoke for search and game matching, entirely on temporary local data."""
import json
import os
from pathlib import Path
import tempfile
import threading
import traceback
from http.server import ThreadingHTTPServer


def run(root):
    from playwright.sync_api import expect, sync_playwright
    os.environ['MEDIAHUB_DATA_DIR'] = str(root)
    from legacy import app, gamesweep

    games_root = root / 'games'
    games_root.mkdir()
    for name in ('CollegeTraits v1.0', 'College Traits v1.1', 'College Traits 2 v1.0'):
        (games_root / name).mkdir()
    app.sql("insert into items(id,title,author,topic,kind,path,url,info) values(1,?,?,?,?,?,?,?)",
            ('CollegeTraits', '', '', 'game', '', 'game:collegetraits', json.dumps({})))
    app.sql("insert into items(id,title,author,topic,kind,path,url) values(2,?,?,?,?,?,?)",
            ('College Traits', '', '', 'video', '', 'video:college'))
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
                for term in ('CollegeTraits', 'College Traits'):
                    q.fill('неттакойигры')
                    expect(page.locator('#lib')).to_contain_text('Ничего не нашлось')
                    q.fill(term)
                    expect(page.locator('#lib')).to_contain_text('CollegeTraits')
                    expect(page.locator('#lib')).to_contain_text('College Traits')
                page.get_by_role('navigation').get_by_role('link', name='Игры').click()
                gq = page.locator('#gq')
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
