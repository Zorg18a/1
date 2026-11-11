"""Headless Edge preflight with temporary data and no real downloads."""
import os
from pathlib import Path
import tempfile
import threading
import traceback
from http.server import ThreadingHTTPServer


def run(root):
    from playwright.sync_api import expect, sync_playwright
    from scripts.browser_diagnostics import BrowserDiagnostics
    os.environ['MEDIAHUB_DATA_DIR'] = str(root)
    from legacy import app
    downloads = root / 'downloads'; downloads.mkdir()
    app.cfg['folder'] = str(downloads)
    server = ThreadingHTTPServer(('127.0.0.1', 0), app.H)
    thread = threading.Thread(target=server.serve_forever); thread.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel='msedge', headless=True)
            diagnostics = None
            try:
                page = browser.new_page(viewport={'width': 320, 'height': 800})
                diagnostics = BrowserDiagnostics(page)
                page.goto(f'http://127.0.0.1:{server.server_port}/', wait_until='domcontentloaded')
                page.wait_for_function("document.querySelector('#disk').textContent.includes('Свободно')")
                before_dialog = sorted(path.name for path in downloads.iterdir())
                requests = []
                page.on('request', lambda request: requests.append(request.url) if request.url.endswith('/api/add') else None)
                page.get_by_role('button', name='Добавить', exact=True).click()
                dialog = page.locator('#addDlg')
                urls = dialog.get_by_label('Ссылки'); urls.fill('https://example.invalid/test')
                details = dialog.locator('details').filter(has_text='Проверка условий загрузки (необязательно)')
                expect(details.locator('li')).to_have_count(0)
                details.locator('summary').focus(); page.keyboard.press('Enter')
                action = details.get_by_role('button', name='Проверить условия загрузки')
                action.focus(); page.keyboard.press('Enter')
                expect(details.get_by_role('status')).to_contain_text('не гарантирует успешную загрузку')
                expect(details.locator('li')).to_have_count(5)
                expect(details.locator('li').first).to_contain_text(str(downloads))
                assert dialog.evaluate('e => e.scrollWidth <= e.clientWidth + 1')
                assert urls.input_value() == 'https://example.invalid/test' and requests == [] and not app.jobs
                assert sorted(path.name for path in downloads.iterdir()) == before_dialog
                dialog.get_by_role('button', name='Отмена').click()
                page.get_by_role('button', name='Добавить', exact=True).click()
                assert not details.evaluate("e => e.open")
                expect(details.locator('li')).to_have_count(0)
                expect(urls).to_have_value('https://example.invalid/test')
                dialog.get_by_role('button', name='Отмена').click()
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
            except Exception:
                text = traceback.format_exc() + '\nBrowser diagnostics:\n' + (diagnostics.report() if diagnostics else '(page not created)')
                if os.environ.get('GITHUB_ACTIONS'):
                    text = text[-6000:].replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A')
                    print(f'::error title=Preflight Edge smoke failed::{text}', flush=True)
                raise
            finally:
                browser.close()
    finally:
        server.shutdown(); server.server_close(); thread.join(); app.db.close()


if __name__ == '__main__':
    with tempfile.TemporaryDirectory() as folder:
        run(Path(folder).resolve())
