"""Edge ZIP metadata listing smoke, using only temporary games and archives."""
import json
import os
from pathlib import Path
import tempfile
import threading
import traceback
import zipfile
from core.local_http import LocalHTTPServer as ThreadingHTTPServer


def run(root):
    from playwright.sync_api import expect, sync_playwright
    from scripts.browser_diagnostics import BrowserDiagnostics
    os.environ['MEDIAHUB_DATA_DIR'] = str(root)
    from legacy import app
    downloads = root / 'downloads'; downloads.mkdir()
    games = root / 'games'; games.mkdir()
    game = games / 'Example Game v1'; game.mkdir()
    save = game / 'save.sav'; save.write_bytes(b'original-save')
    incoming = downloads / 'Incoming_Downloads'; incoming.mkdir()
    archive = incoming / 'Example Game v2.zip'
    with zipfile.ZipFile(archive, 'w') as z:
        for i in range(205): z.writestr(f'game/file{i:03}.txt', b'fixture')
    before = archive.read_bytes()
    app.cfg['folder'] = str(downloads); app.cfg['games_root'] = str(games)
    info = {'inst': {'version': '1'}, 'meta': {'version': '2'}, 'update': True}
    app.sql('insert into items(id,title,kind,path,url,info) values(1,?,?,?,?,?)',
            ('Example Game', 'game', str(game), 'game:examplegame', json.dumps(info)))
    server = ThreadingHTTPServer(('127.0.0.1', 0), app.H)
    thread = threading.Thread(target=server.serve_forever); thread.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel='msedge', headless=True)
            diagnostics = None
            try:
                page = browser.new_page(viewport={'width': 320, 'height': 800})
                diagnostics = BrowserDiagnostics(page)
                requests = []
                page.on('request', lambda r: requests.append(r.post_data_json) if r.url.endswith('/api/game/zip-inspect') else None)
                page.goto(f'http://127.0.0.1:{server.server_port}/#games', wait_until='domcontentloaded')
                page.locator('.gcard').focus(); page.keyboard.press('Enter')
                panel = page.locator('#gpanel')
                action = panel.get_by_role('button', name='Проверить метаданные ZIP: Example Game v2.zip')
                expect(action).to_be_visible(); assert requests == []
                action.focus(); page.keyboard.press('Enter')
                item = panel.locator('.update-results > ul > li').first
                expect(item.get_by_role('status')).to_contain_text('CRC не проверены')
                expect(item).to_contain_text('только первые 200')
                expect(item.locator('ul li')).to_have_count(200)
                expect(item.locator('ul li').first).to_have_text('game/file000.txt (файл)')
                assert requests[0]['list_names'] is True and len(requests) == 1
                assert archive.read_bytes() == before and save.read_bytes() == b'original-save'
                assert sorted(p.name for p in incoming.iterdir()) == [archive.name]
                assert panel.evaluate('e => e.scrollWidth <= e.clientWidth + 1')
                with archive.open('ab') as stream: stream.write(b'x')
                action.click(); expect(item.get_by_role('status')).to_contain_text('Архив изменился')
                expect(item.locator('ul li')).to_have_count(0)
                assert save.read_bytes() == b'original-save' and archive.read_bytes() == before + b'x'
                print('Edge: optional bounded ZIP listing, stale identity and unchanged files passed')
            except Exception:
                text = traceback.format_exc() + '\nBrowser diagnostics:\n' + (diagnostics.report() if diagnostics else '(page not created)')
                if os.environ.get('GITHUB_ACTIONS'):
                    text = text[-6000:].replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A')
                    print(f'::error title=ZIP listing Edge smoke failed::{text}', flush=True)
                raise
            finally:
                browser.close()
    finally:
        server.shutdown(); server.server_close(); thread.join(); app.db.close()


if __name__ == '__main__':
    with tempfile.TemporaryDirectory() as directory:
        run(Path(directory).resolve())
