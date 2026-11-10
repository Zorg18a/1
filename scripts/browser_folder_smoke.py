"""Edge smoke for explicitly choosing nested game folders; temporary data only."""
import os
from pathlib import Path
import tempfile
import threading
import traceback
from http.server import ThreadingHTTPServer


def run(root):
    from playwright.sync_api import expect, sync_playwright
    os.environ['MEDIAHUB_DATA_DIR'] = str(root)
    from legacy import app

    games = root / 'games'
    for name in ('College Traits v1.0', 'CollegeTraits v1.1'):
        folder = games / 'Категория' / name
        (folder / 'saves').mkdir(parents=True)
        (folder / 'saves' / 'slot.sav').write_bytes(b'save')
        (folder / 'game.exe').write_bytes(b'game')
    app.cfg['games_root'] = str(games)
    app.cfg['folder'] = str(root / 'downloads')
    server = ThreadingHTTPServer(('127.0.0.1', 0), app.H)
    thread = threading.Thread(target=server.serve_forever); thread.start()
    gs = app.games_server(); original = gs.store.on_done; finished = threading.Event()
    def done(entries, path):
        try: original(entries, path)
        finally: finished.set()
    gs.store.on_done = done
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel='msedge', headless=True)
            try:
                page = browser.new_page(viewport={'width': 1100, 'height': 800})
                page.goto(f'http://127.0.0.1:{server.server_port}/#settings', wait_until='domcontentloaded')
                layout = page.locator('#s_games_layout')
                expect(layout).to_be_enabled()
                layout.select_option('nested')
                expect(page.locator('#s_games_layout').locator('xpath=ancestor::div[contains(@class,"sr")]')).to_contain_text('пересканировать сейчас')
                assert app.cfg['games_layout'] == 'nested'
                page.goto(app.games_url(), wait_until='domcontentloaded')
                expect(page.locator('#root')).to_have_value(str(games))
                page.locator('#layout').select_option('nested')
                page.locator('#scan').click()
                assert finished.wait(10), 'GameSweep scan did not finish'
                expect(page.locator('#c1')).to_have_text('2')
                expect(page.locator('#c2')).to_have_text('1')
                expect(page.locator('#list')).to_contain_text('College Traits')
                assert {entry['name'] for entry in gs.store.games} == {'College Traits v1.0', 'CollegeTraits v1.1'}
                rows = app.sql("select title from items where kind='game'")
                assert len(rows) == 1 and rows[0]['title'] == 'CollegeTraits', [dict(row) for row in rows]
                assert (games / 'Категория' / 'College Traits v1.0' / 'saves' / 'slot.sav').read_bytes() == b'save'
                print('Edge: folder-layout setting and nested scan passed')
            finally:
                browser.close()
    finally:
        server.shutdown(); server.server_close(); thread.join()
        gs.shutdown(); gs.server_close(); app.db.close()


if __name__ == '__main__':
    try:
        with tempfile.TemporaryDirectory() as directory:
            run(Path(directory).resolve())
    except Exception:
        if os.environ.get('GITHUB_ACTIONS'):
            text = traceback.format_exc()[-6000:].replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A')
            print(f'::error title=Headless Edge folder scan failed::{text}', flush=True)
        raise
