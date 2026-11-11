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
    second = manga / 'chapters' / '13'
    second.mkdir(parents=True)
    (second / '001.png').write_bytes(PNG)
    manifest = {'slug': 'reader-test', 'title': 'Тест читалки',
                'listed': [{'cid': '12', 'label': 'Глава 1'}, {'cid': '13', 'label': 'Глава 2'}],
                'chapters': {key: {'label': label, 'files': ['001.png'], 'expected': 1, 'done': True}
                             for key, label in (('12', 'Глава 1'), ('13', 'Глава 2'))}}
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
                page.route('**/api/progress', lambda route: route.abort())
                page.evaluate("window.dispatchEvent(new Event('scroll'))")
                save_retry = page.get_by_role('button', name='Повторить сохранение позиции')
                expect(save_retry).to_be_visible()
                expect(page.locator('#reader-progress-status')).to_contain_text('Запрос мог выполниться')
                with page.expect_event('dialog') as warning:
                    page.evaluate('setTimeout(() => location.reload(), 0)')
                assert warning.value.type == 'beforeunload'
                warning.value.dismiss()
                expect(save_retry).to_be_visible()
                page.unroute('**/api/progress')
                save_retry.focus(); page.keyboard.press('Enter')
                expect(save_retry).to_be_hidden()
                expect(page.locator('#reader-progress-status')).to_have_text('Позиция сохранена.')
                expect(page.locator('#v')).to_be_focused()
                page.locator('#n').click()
                page.wait_for_function("""async () => {
                    const r = await fetch('/api/manga/3'); const data = await r.json();
                    return data.progress?.cid === '13' && data.progress?.page === 0;
                }""")
                page.reload()
                expect(page.locator('#c')).to_have_value('1')
                assert app.sql("select cid,page from progress where slug='reader-test'")[0]['cid'] == '13'
                page.close()
                app.sql("update items set url='manga:other' where id=3")
                page = browser.new_page(viewport={'width': 320, 'height': 800})
                writes = []
                page.on('request', lambda request: writes.append(request.url) if request.url.endswith('/api/progress') else None)
                page.goto(f'http://127.0.0.1:{server.server_port}/m/3', wait_until='domcontentloaded')
                expect(page.locator('#reader-error')).to_contain_text('Позиция не сохраняется')
                expect(page.locator('#v img')).to_be_visible()
                page.locator('#p').click()
                page.evaluate("window.dispatchEvent(new Event('scroll'))")
                page.wait_for_timeout(900)
                assert writes == []
                assert app.sql("select cid from progress where slug='reader-test'")[0]['cid'] == '13'
                assert not app.sql("select * from progress where slug='other'")
                page.close()
                app.sql("update items set url='manga:reader-test' where id=3")
                page = browser.new_page(viewport={'width': 320, 'height': 800})
                page.goto(f'http://127.0.0.1:{server.server_port}/m/3', wait_until='domcontentloaded')
                expect(page.locator('#v img')).to_be_visible()
                page.wait_for_timeout(900)
                app.sql("update items set url='manga:other' where id=3")
                page.locator('#p').click()
                expect(page.locator('#reader-progress-status')).to_contain_text('Запись манги изменилась')
                expect(page.get_by_role('button', name='Повторить сохранение позиции')).to_be_hidden()
                assert app.sql("select cid from progress where slug='reader-test'")[0]['cid'] == '13'
                assert not app.sql("select * from progress where slug='other'")
                print('Edge: reader retry, chapter save and identity mismatch protection passed')
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
