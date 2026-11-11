"""Headless Edge preflight with temporary data and no real downloads."""
import os
from pathlib import Path
import tempfile
import threading
from http.server import ThreadingHTTPServer


def run(root):
    from playwright.sync_api import expect, sync_playwright
    os.environ['MEDIAHUB_DATA_DIR'] = str(root)
    from legacy import app
    downloads = root / 'downloads'; downloads.mkdir()
    app.cfg['folder'] = str(downloads)
    server = ThreadingHTTPServer(('127.0.0.1', 0), app.H)
    thread = threading.Thread(target=server.serve_forever); thread.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel='msedge', headless=True)
            try:
                page = browser.new_page(viewport={'width': 320, 'height': 800})
                page.goto(f'http://127.0.0.1:{server.server_port}/', wait_until='domcontentloaded')
                page.get_by_role('navigation').get_by_role('link', name='Настройки').click()
                folder = page.get_by_label('Папка загрузок')
                expect(folder).to_have_value(str(downloads))
                panel = page.get_by_role('heading', name='Проверка перед загрузкой').locator('..')
                expect(panel).to_contain_text('Права на запись')
                assert panel.evaluate('e => e.scrollWidth <= e.clientWidth + 1')
                button = panel.get_by_role('button', name='Проверить условия загрузки')
                expect(panel.locator('li')).to_have_count(0)
                page.wait_for_function("document.querySelector('#disk').textContent.includes('Свободно')")
                before = sorted(path.name for path in downloads.iterdir())
                before_jobs = len(app.jobs)
                button.focus(); page.keyboard.press('Enter')
                expect(panel.get_by_role('status')).to_contain_text('не гарантирует успешную загрузку')
                expect(panel.locator('li')).to_have_count(4)
                expect(panel.locator('li').first).to_contain_text('существует')
                expect(panel).to_contain_text('ffmpeg:')
                assert len(app.jobs) == before_jobs and sorted(path.name for path in downloads.iterdir()) == before
                page.route('**/api/preflight', lambda route: route.abort())
                button.click(); expect(panel.get_by_role('status')).to_contain_text('Проверка не выполнена')
                expect(button).to_be_enabled()
                page.unroute('**/api/preflight')
                button.click(); expect(panel.get_by_role('status')).to_contain_text('Проверка завершена')
                print('Edge: read-only preflight, failure, retry and 320px passed')
            finally:
                browser.close()
    finally:
        server.shutdown(); server.server_close(); thread.join(); app.db.close()


if __name__ == '__main__':
    with tempfile.TemporaryDirectory() as folder:
        run(Path(folder).resolve())
