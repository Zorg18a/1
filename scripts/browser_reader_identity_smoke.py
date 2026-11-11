"""Edge reader root-change protection using temporary databases and manga files."""
import base64
import json
import os
from pathlib import Path
import tempfile
import threading
import traceback
from http.server import ThreadingHTTPServer

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4z8AAAAMBAQDJ/pLvAAAAAElFTkSuQmCC')


def run(base):
    from playwright.sync_api import expect, sync_playwright
    os.environ['MEDIAHUB_DATA_DIR'] = str(base)
    from legacy import app

    roots = [base / 'first', base / 'second']
    manifest = {'slug': 'same', 'title': 'Тест',
                'listed': [{'cid': cid, 'label': f'Глава {number}'} for cid, number in (('12', 1), ('13', 2))],
                'chapters': {cid: {'label': f'Глава {number}', 'files': ['001.png'], 'expected': 1, 'done': True}
                             for cid, number in (('12', 1), ('13', 2))}}
    for root in roots:
        for cid in ('12', '13'):
            directory = root / 'chapters' / cid; directory.mkdir(parents=True)
            (directory / '001.png').write_bytes(PNG)
        (root / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False), encoding='utf8')
    app.sql("insert into items(id,title,kind,root,url) values(1,'Тест','manga',?,'manga:same')", (str(roots[0]),))
    app.sql("insert into progress values('same','12',0)")
    server = ThreadingHTTPServer(('127.0.0.1', 0), app.H)
    thread = threading.Thread(target=server.serve_forever); thread.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel='msedge', headless=True)
            try:
                page = browser.new_page(viewport={'width': 320, 'height': 800})
                image_responses = []
                page.on('response', lambda response: image_responses.append(response.status) if '/mi/1/13/' in response.url else None)
                url = f'http://127.0.0.1:{server.server_port}/m/1'
                page.goto(url, wait_until='domcontentloaded')
                expect(page.locator('#c')).to_have_value('0'); page.wait_for_timeout(900)
                app.sql('update items set root=? where id=1', (str(roots[1]),))
                page.locator('#n').click()
                expect(page.locator('#reader-progress-status')).to_contain_text('Последнее сохранение отклонено')
                retry = page.get_by_role('button', name='Повторить загрузку страницы 1')
                expect(retry).to_be_visible()
                assert 409 in image_responses
                with page.expect_response(lambda response: '/mi/1/13/' in response.url and 'retry=' in response.url) as retried:
                    retry.click()
                assert retried.value.status == 409
                expect(page.locator('.reader-image-error')).to_contain_text('Не удалось загрузить страницу 1')
                assert page.locator('#v img').evaluate('img => img.naturalWidth') == 0
                page.get_by_role('button', name='Проверить сохранённую позицию').click()
                expect(page.locator('#reader-conflict-saved')).to_contain_text('Не удалось подтвердить идентичность')
                expect(page.get_by_role('button', name='Сохранить позицию этой вкладки')).to_be_disabled()
                assert tuple(app.sql("select cid,page from progress where slug='same'")[0]) == ('12', 0)
                page.close()
                app.sql('update items set root=? where id=1', (str(roots[0]),))
                page = browser.new_page(viewport={'width': 320, 'height': 800})
                page.goto(url, wait_until='domcontentloaded')
                expect(page.locator('#c')).to_have_value('0'); page.wait_for_timeout(900)
                app.sql("update progress set page=7 where slug='same'")
                page.locator('#n').click()
                expect(page.locator('#reader-progress-status')).to_contain_text('Последнее сохранение отклонено')
                apply = page.get_by_role('button', name='Сохранить позицию этой вкладки')
                apply.scroll_into_view_if_needed(); page.wait_for_timeout(900)
                page.get_by_role('button', name='Проверить сохранённую позицию').click()
                expect(apply).to_be_enabled()
                app.sql('update items set root=? where id=1', (str(roots[1]),))
                page.once('dialog', lambda dialog: dialog.accept()); apply.click()
                expect(page.locator('#reader-conflict-saved')).to_contain_text('Проверьте сохранённую позицию перед выбором')
                assert tuple(app.sql("select cid,page from progress where slug='same'")[0]) == ('12', 7)
                page.get_by_role('button', name='Проверить сохранённую позицию').click()
                expect(page.locator('#reader-conflict-saved')).to_contain_text('Не удалось подтвердить идентичность')
                expect(apply).to_be_disabled()
                page.close()
                page = browser.new_page(viewport={'width': 320, 'height': 800})
                writes = []
                page.on('request', lambda request: writes.append(request.url) if request.url.endswith('/api/progress') else None)
                def omit_identity(route):
                    response = route.fetch(); data = response.json(); data.pop('progress_identity', None)
                    route.fulfill(response=response, json=data)
                page.route('**/api/manga/1', omit_identity)
                page.goto(url, wait_until='domcontentloaded')
                expect(page.locator('#reader-error')).to_contain_text('Позиция не сохраняется')
                expect(page.locator('#v img')).to_be_visible(); page.locator('#n').click()
                page.evaluate("window.dispatchEvent(new Event('scroll'))"); page.wait_for_timeout(900)
                assert not writes
                assert tuple(app.sql("select cid,page from progress where slug='same'")[0]) == ('12', 7)
                page.close()
                page = browser.new_page(viewport={'width': 320, 'height': 800})
                requests = []
                page.on('request', lambda request: requests.append(request.url) if '/mi/' in request.url or request.url.endswith('/api/progress') else None)
                def omit_image_identity(route):
                    response = route.fetch(); data = response.json(); data.pop('image_identity', None)
                    route.fulfill(response=response, json=data)
                page.route('**/api/manga/1', omit_image_identity)
                page.goto(url, wait_until='domcontentloaded')
                expect(page.locator('#reader-error')).to_contain_text('Страницы не загружаются')
                expect(page.locator('#n')).to_be_disabled()
                page.evaluate("window.dispatchEvent(new Event('scroll'))"); page.wait_for_timeout(900)
                assert not requests
                print('Edge: reader folder changes block progress, image requests and conflict confirmation')
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
            print(f'::error title=Headless Edge reader identity failed::{text}', flush=True)
        raise
