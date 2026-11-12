"""Headless Edge queue status smoke with in-memory fake jobs, no downloads."""
import os
from pathlib import Path
import tempfile
import threading
import traceback
from core.local_http import LocalHTTPServer as ThreadingHTTPServer


def run(root):
    from playwright.sync_api import expect, sync_playwright
    from scripts.browser_diagnostics import BrowserDiagnostics
    os.environ['MEDIAHUB_DATA_DIR'] = str(root)
    from legacy import app
    for job_id, title, status in [(1, 'Частичный сайт', 'сохранено частично: достигнут лимит'),
                                   (2, 'Ошибка сети', 'ошибка: сеть'), (3, 'Ожидает', 'в очереди'),
                                   (4, 'Завершено', 'готово')]:
        app.jobs[job_id] = {'id': job_id, 'url': 'https://example.invalid', 'kind': 'video',
                            'status': status, 'title': title, 'pct': 100, 'speed': 0, 'eta': 0,
                            'cancel': False, 'daily': False, 'start_at': 0}
    server = ThreadingHTTPServer(('127.0.0.1', 0), app.H)
    thread = threading.Thread(target=server.serve_forever); thread.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel='msedge', headless=True)
            diagnostics = None
            try:
                page = browser.new_page(viewport={'width': 320, 'height': 800})
                diagnostics = BrowserDiagnostics(page)
                actions = []
                page.on('request', lambda r: actions.append(r.url) if r.method == 'POST' and
                        any(r.url.endswith(p) for p in ('/api/add', '/api/cancel', '/api/clear')) else None)
                page.goto(f'http://127.0.0.1:{server.server_port}/#downloads', wait_until='domcontentloaded')
                summary = page.locator('#v-downloads .queue-summary')
                expect(summary).to_contain_text('в очереди — 1')
                expect(summary).to_contain_text('частично — 1')
                expect(summary).to_contain_text('с ошибкой — 1')
                expect(summary).to_contain_text('готово/сохранено — 1')
                expect(summary).to_contain_text('проверьте очередь, библиотеку')
                expect(page.locator('.job').filter(has_text='Частичный сайт').locator('.js')).to_have_class('js part')
                expect(page.locator('.job').filter(has_text='Ошибка сети').locator('.js')).to_have_class('js err')
                page.route('**/api/jobs', lambda route: route.abort())
                expect(summary).to_contain_text('могло устареть', timeout=18000)
                expect(summary).to_contain_text('фоновые вкладки')
                page.unroute('**/api/jobs')
                expect(summary).not_to_contain_text('могло устареть', timeout=10000)
                race = page.evaluate('''async () => {
                  const original = window.fetch, waiting = [];
                  const fake = status => new Response(JSON.stringify([{ id: 999, title: 'Race', kind: 'video',
                    status, pct: 0, speed: 0, eta: 0 }]), {headers: {'Content-Type': 'application/json'}});
                  window.fetch = (url, opts) => url === '/api/jobs' ? new Promise(resolve => waiting.push(resolve)) : original(url, opts);
                  try {
                    const old = poll(), newer = poll();
                    waiting[1](fake('готово')); await newer;
                    const fresh = document.querySelector('.queue-summary').textContent;
                    waiting[0](fake('в очереди')); await old;
                    return [fresh, document.querySelector('.queue-summary').textContent];
                  } finally { window.fetch = original; }
                }''')
                assert 'готово/сохранено — 1' in race[0] and race[0] == race[1]
                assert not actions and len(app.jobs) == 4 and not any(j['cancel'] for j in app.jobs.values())
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
                print('Edge: partial/error summary, stale response and recovery passed')
            except Exception:
                text = traceback.format_exc() + '\nBrowser diagnostics:\n' + (diagnostics.report() if diagnostics else '(page not created)')
                if os.environ.get('GITHUB_ACTIONS'):
                    text = text[-6000:].replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A')
                    print(f'::error title=Queue summary Edge smoke failed::{text}', flush=True)
                raise
            finally:
                browser.close()
    finally:
        server.shutdown(); server.server_close(); thread.join(); app.db.close()


if __name__ == '__main__':
    with tempfile.TemporaryDirectory() as directory:
        run(Path(directory).resolve())
