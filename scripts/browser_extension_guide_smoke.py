"""Edge setup guide smoke on temporary data, no real extension or internet."""
import os
from pathlib import Path
import tempfile
import threading
import time
import traceback
from http.server import ThreadingHTTPServer


def run(root):
    from playwright.sync_api import expect, sync_playwright
    from scripts.browser_diagnostics import BrowserDiagnostics
    os.environ['MEDIAHUB_DATA_DIR'] = str(root)
    from legacy import app
    server = ThreadingHTTPServer(('127.0.0.1', 0), app.H)
    thread = threading.Thread(target=server.serve_forever); thread.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel='msedge', headless=True)
            diagnostics = None
            try:
                page = browser.new_page(viewport={'width': 320, 'height': 800})
                diagnostics = BrowserDiagnostics(page)
                writes = []
                page.on('request', lambda r: writes.append(r.url) if r.method == 'POST' and
                        any(r.url.endswith(p) for p in ('/api/ext/approve', '/ext/tabs', '/api/add')) else None)
                page.goto(f'http://127.0.0.1:{server.server_port}/#settings', wait_until='domcontentloaded')
                guide = page.locator('#extension-guide')
                browser_choice = guide.get_by_label('Ваш браузер')
                expect(browser_choice).to_be_visible()
                browser_choice.select_option('firefox')
                expect(guide.locator('ol')).to_contain_text('about:debugging')
                expect(guide.locator('ol')).to_contain_text('перезапуска Firefox')
                browser_choice.select_option('edge')
                expect(guide.locator('ol')).to_contain_text('edge://extensions')
                expect(guide).to_contain_text('могут закрыться')
                button = guide.get_by_role('button', name='Обновить состояние подключения')
                button.focus(); page.keyboard.press('Enter')
                status = guide.get_by_role('status')
                expect(status).to_contain_text('сохранённых разрешений — 0, ожидающих запросов — 0')
                expect(status).to_contain_text('не статус выбранного браузера')
                assert not writes and not app.jobs
                origin = 'chrome-extension://test-choose-manually'
                app.PAIR[origin] = {'name': 'Тест', 't': time.time()}
                button.click()
                expect(status).to_contain_text('ожидающих запросов — 1')
                expect(page.locator('#pairBar')).to_be_visible(timeout=10000)
                page.locator('#pairBar').get_by_role('button', name='Отклонить').click()
                page.wait_for_function("!document.querySelector('#pairBar').offsetParent")
                assert origin not in app.PAIR and origin not in app.EXT
                button.click(); expect(status).to_contain_text('ожидающих запросов — 0')
                expect(status).to_contain_text('отклонено или запрос истёк')
                page.route('**/api/ext', lambda route: route.abort())
                button.click(); expect(status).to_contain_text('Состояние неизвестно')
                expect(button).to_be_enabled()
                page.unroute('**/api/ext')
                button.click(); expect(status).to_contain_text('сохранённых разрешений — 0')
                assert len(writes) == 1 and writes[0].endswith('/api/ext/approve') and not app.jobs
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
                print('Edge: browser instructions, explicit status, rejection and retry passed')
            except Exception:
                text = traceback.format_exc() + '\nBrowser diagnostics:\n' + (diagnostics.report() if diagnostics else '(page not created)')
                if os.environ.get('GITHUB_ACTIONS'):
                    text = text[-6000:].replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A')
                    print(f'::error title=Extension guide Edge smoke failed::{text}', flush=True)
                raise
            finally:
                browser.close()
    finally:
        server.shutdown(); server.server_close(); thread.join(); app.db.close()


if __name__ == '__main__':
    with tempfile.TemporaryDirectory() as directory:
        run(Path(directory).resolve())
