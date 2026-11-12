"""Edge: interrupt and continue 86 synthetic game checks with a simulated extension."""
import json
import os
from pathlib import Path
import tempfile
import threading
import traceback

from core.local_http import LocalHTTPServer


def run(root):
    from playwright.sync_api import expect, sync_playwright
    os.environ['MEDIAHUB_DATA_DIR'] = str(root)
    os.environ['MEDIAHUB_GAME_DELAY'] = '0'
    from legacy import app
    for i in range(1, 87):
        info = json.dumps({'meta': {'thread': f'https://example.com/{i}', 'version': '1'}})
        app.sql("insert into items(id,title,kind,path,root,url,info) values(?,?,'game','','',?,?)",
                (i, f'Game {i}', f'game:{i}', info))
    seen = []
    app.ext_online = lambda: True
    def fetch(url, job):
        seen.append(url)
        if len(seen) == 2: raise RuntimeError('simulated timeout')
        if len(seen) == 3: job['cancel'] = True
        return 'page'
    app.fetch_html = fetch
    app.gamelib.parse_thread = lambda html, url: {'name': 'Game', 'version': '1'}
    app.apply_meta = lambda meta, thread: None
    app.scheduler.spawn_workers(1)
    server = LocalHTTPServer(('127.0.0.1', 0), app.H)
    thread = threading.Thread(target=server.serve_forever); thread.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel='msedge', headless=True)
            try:
                page = browser.new_page(viewport={'width': 320, 'height': 800})
                page.goto(f'http://127.0.0.1:{server.server_port}/', wait_until='domcontentloaded')
                page.get_by_role('navigation').get_by_role('link', name='Игры').click()
                page.locator('#gchk').click()
                page.get_by_role('navigation').get_by_role('link', name='Загрузки').click()
                section = page.locator('.game-check-resume')
                resume = section.get_by_role('button', name='Продолжить оставшиеся темы задания 1')
                expect(resume).to_be_visible(timeout=15000)
                expect(section).to_contain_text('Всего 86, проверено 2, осталось 83, ошибок или неизвестно 1')
                resume.click()
                expect(section).to_contain_text('Всего 86, проверено 85, осталось 0, ошибок или неизвестно 1', timeout=20000)
                assert len(seen) == 86 and len(set(seen)) == 86, seen
                assert section.evaluate('e => e.scrollWidth <= e.clientWidth + 1')
                print('Edge: explicit session continuation of 86 game checks passed')
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
            print(f'::error title=Game check continuation Edge smoke failed::{text}', flush=True)
        raise
