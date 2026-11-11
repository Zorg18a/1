"""Headless Edge backup download against temporary data only."""
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import traceback
from http.server import ThreadingHTTPServer


def run(root):
    from playwright.sync_api import expect, sync_playwright
    os.environ['MEDIAHUB_DATA_DIR'] = str(root)
    from legacy import app
    app.sql("insert into items(id,title,kind,path,url) values(55,'Резервный тест','video','missing','backup-test')")
    app.sql('pragma journal_mode=wal')
    app.sql("update items set title='Данные из WAL' where id=55")
    server = ThreadingHTTPServer(('127.0.0.1', 0), app.H)
    thread = threading.Thread(target=server.serve_forever); thread.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel='msedge', headless=True)
            try:
                page = browser.new_page(viewport={'width': 320, 'height': 800}, accept_downloads=True)
                page.goto(f'http://127.0.0.1:{server.server_port}/', wait_until='domcontentloaded')
                page.get_by_role('navigation').get_by_role('link', name='Настройки').click()
                panel = page.get_by_role('heading', name='Резервная копия базы').locator('..')
                expect(panel).to_contain_text('Медиафайлы')
                assert panel.evaluate('e => e.scrollWidth <= e.clientWidth + 1')
                button = panel.get_by_role('button', name='Скачать копию базы')
                with page.expect_download(timeout=30000) as event:
                    button.click()
                download = event.value
                assert download.suggested_filename.startswith('mediahub-library-')
                path = root / 'downloaded.db'; download.save_as(str(path))
                with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
                    assert db.execute('select title from items where id=55').fetchone()[0] == 'Данные из WAL'
                    assert db.execute('pragma integrity_check').fetchone()[0] == 'ok'
                statuses = panel.get_by_role('status')
                expect(statuses.nth(0)).to_contain_text('Проверьте загрузки')
                app.sql("update items set title='Позже' where id=55")
                panel.get_by_label('Файл копии для проверки').set_input_files(str(path))
                panel.get_by_role('button', name='Проверить копию').click()
                expect(statuses.nth(1)).to_contain_text('Целостность и минимальная структура проверены')
                expect(statuses.nth(1)).to_contain_text('восстановление не выполнялось')
                invalid = root / 'invalid.db'; invalid.write_bytes(b'x' * 100)
                panel.get_by_label('Файл копии для проверки').set_input_files(str(invalid))
                panel.get_by_role('button', name='Проверить копию').click()
                expect(statuses.nth(1)).to_contain_text('Проверка не выполнена')
                page.route('**/api/backup', lambda route: route.abort())
                button.click()
                expect(statuses.nth(0)).to_contain_text('Не удалось скачать копию')
                expect(button).to_be_enabled()
                assert app.sql('select title from items where id=55')[0]['title'] == 'Позже'
                print('Edge: database download, inspection and error handling passed')
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
            print(f'::error title=Headless Edge backup smoke failed::{text}', flush=True)
        raise
