"""Exercise pasted links and site page selection in Edge, without real downloads."""
import os
from pathlib import Path
import tempfile
import threading

from core.local_http import LocalHTTPServer


def run(root):
    from playwright.sync_api import expect, sync_playwright
    os.environ['MEDIAHUB_DATA_DIR'] = str(root)
    from legacy import app
    urls = [f'https://example.invalid/page-{i}' for i in range(83)]
    app.cfg['folder'] = str(root / 'downloads')
    def discover(token, data):
        app.prev[token].update(pages=[{'url': url, 'title': url, 'depth': 0} for url in urls],
                               done=len(urls), total=len(urls), finished=True)
    app.discover = discover
    server = LocalHTTPServer(('127.0.0.1', 0), app.H)
    thread = threading.Thread(target=server.serve_forever); thread.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel='msedge', headless=True)
            try:
                page = browser.new_page(viewport={'width': 800, 'height': 900})
                page.goto(f'http://127.0.0.1:{server.server_port}/', wait_until='domcontentloaded')
                page.get_by_role('button', name='Добавить', exact=True).click()
                dialog = page.locator('#addDlg')
                dialog.get_by_label('Ссылки').fill('\n'.join(urls))
                dialog.locator('#go').click()
                expect(dialog).not_to_be_visible()
                assert len(app.jobs) == 83 and [j['url'] for j in app.jobs.values()] == urls
                app.jobs.clear()
                while not app.scheduler.pending.empty(): app.scheduler.pending.get_nowait()
                page.get_by_role('button', name='Добавить', exact=True).click()
                dialog.get_by_label('Ссылки').fill('\n'.join(urls))
                dialog.get_by_role('radio', name='Сайт').click()
                dialog.locator('#more summary').click()
                dialog.get_by_role('button', name='Найти страницы').click()
                expect(dialog.locator('#fcount')).to_have_text('Найдено 83, выбрано 83')
                expect(dialog.locator('#plist input:checked')).to_have_count(83)
                page.once('dialog', lambda prompt: prompt.dismiss()); dialog.locator('#go').click()
                assert not app.jobs
                page.once('dialog', lambda prompt: prompt.accept()); dialog.locator('#go').click()
                expect(dialog).not_to_be_visible()
                queued = list(app.jobs.values())
                assert len(queued) == 83 and [j['url'] for j in queued] == urls
                assert queued[0]['sel'] == urls and all(not j['sel'] for j in queued[1:])
                print('Edge: 83 pasted links, all 83 site pages, consent and queue passed')
            finally:
                browser.close()
    finally:
        server.shutdown(); server.server_close(); thread.join(); app.db.close()


if __name__ == '__main__':
    with tempfile.TemporaryDirectory() as directory:
        run(Path(directory).resolve())
