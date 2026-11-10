"""Headless Edge reader image-retry smoke using only temporary files."""
import base64
import json
import os
from pathlib import Path
import tempfile
import threading
import traceback
from http.server import ThreadingHTTPServer

# One valid one-pixel PNG; the file is created only after the first failed load.
PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4z8AAAAMBAQDJ/pLvAAAAAElFTkSuQmCC')


def run(root):
    from playwright.sync_api import expect, sync_playwright
    os.environ['MEDIAHUB_DATA_DIR'] = str(root)
    from legacy import app

    manga = root / 'manga'
    chapter = manga / 'chapters' / '12'
    chapter.mkdir(parents=True)
    manifest = {'slug': 'reader-test', 'title': 'Тест читалки',
                'listed': [{'cid': '12', 'label': 'Глава 1'}],
                'chapters': {'12': {'label': 'Глава 1', 'files': ['001.png'], 'expected': 1, 'done': True}}}
    (manga / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False), encoding='utf8')
    app.sql("insert into items(id,title,kind,path,root,url) values(3,'Тест','manga',?,?,?)",
            (str(chapter / '001.png'), str(manga), 'manga:reader-test'))
    server = ThreadingHTTPServer(('127.0.0.1', 0), app.H)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel='msedge', headless=True)
            try:
                page = browser.new_page(viewport={'width': 320, 'height': 800})
                page.goto(f'http://127.0.0.1:{server.server_port}/m/3', wait_until='domcontentloaded')
                retry = page.get_by_role('button', name='Повторить загрузку страницы 1')
                expect(retry).to_be_visible()
                expect(page.locator('.reader-image-error')).to_contain_text('Проверьте файл и подключение')
                assert page.locator('.reader-image-error').evaluate('e => e.scrollWidth <= e.clientWidth + 1')
                retry.focus(); page.keyboard.press('Enter')
                expect(page.locator('.reader-image-error')).to_contain_text('Не удалось загрузить страницу 1')
                (chapter / '001.png').write_bytes(PNG)
                retry.focus(); page.keyboard.press('Enter')
                expect(retry).to_be_hidden()
                image = page.locator('#v img')
                page.wait_for_function("document.querySelector('#v img')?.naturalWidth > 0")
                expect(image).to_be_focused()
                print('Edge: missing reader page, keyboard retry and focus passed')
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
            print(f'::error title=Headless Edge reader smoke failed::{text}', flush=True)
        raise
