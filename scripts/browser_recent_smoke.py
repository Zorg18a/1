"""Exercise opening history and stale-identity refusal in Edge with temporary data."""
import json
import os
from pathlib import Path
import tempfile
import threading
import wave
from http.server import ThreadingHTTPServer


def run(root):
    from playwright.sync_api import expect, sync_playwright
    os.environ['MEDIAHUB_DATA_DIR'] = str(root)
    from legacy import app
    audio = root / 'audio.wav'
    with wave.open(str(audio), 'wb') as sound:
        sound.setnchannels(1); sound.setsampwidth(2); sound.setframerate(8000)
        sound.writeframes(bytes(16000))
    manga = root / 'manga'; manga.mkdir()
    (manga / 'manifest.json').write_text(json.dumps({'slug': 'test', 'title': 'Манга', 'listed': [], 'chapters': {}}), encoding='utf8')
    app.sql("insert into items(id,title,kind,path,root,url) values(1,'Аудио','audio',?,'','audio:test'),(2,'Манга','manga','',?,'manga:test')", (str(audio), str(manga)))
    server = ThreadingHTTPServer(('127.0.0.1', 0), app.H)
    thread = threading.Thread(target=server.serve_forever); thread.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel='msedge', headless=True)
            try:
                page = browser.new_page(viewport={'width': 320, 'height': 800})
                base = f'http://127.0.0.1:{server.server_port}'
                page.goto(base + '/p/1')
                expect(page.locator('#player-title')).to_have_text('Аудио')
                page.wait_for_function("JSON.parse(localStorage.getItem('mediahub.recent.v1') || '[]').length === 1")
                page.goto(base + '/m/2')
                expect(page.locator('#v')).to_have_text('Нет доступных глав')
                page.wait_for_function("JSON.parse(localStorage.getItem('mediahub.recent.v1') || '[]').length === 2")
                page.goto(base + '/')
                recent = page.locator('section[aria-labelledby="recent-heading"]')
                expect(recent.get_by_role('button', name='Читалка: Манга')).to_be_visible()
                expect(recent.get_by_role('button', name='Плеер: Аудио')).to_be_visible()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
                recent.get_by_role('button', name='Читалка: Манга').click()
                expect(page).to_have_url(__import__('re').compile(r'/m/2\?recent=[0-9a-f]{64}$'))
                expect(page.locator('#v')).to_have_text('Нет доступных глав')
                page.goto(base + '/')
                expect(recent.get_by_role('button', name='Плеер: Аудио')).to_be_visible()
                app.sql("update items set url='audio:changed' where id=1")
                recent.get_by_role('button', name='Плеер: Аудио').click()
                expect(recent.locator('[role=status]')).to_contain_text('изменился')
                assert page.url == base + '/'
                page.reload()
                expect(recent.get_by_role('button', name='Плеер: Аудио')).to_have_count(0)
                old_token = '0' * 64
                page.goto(base + '/p/1?recent=' + old_token)
                expect(page.locator('#player-error')).to_be_visible()
                assert page.locator('#player-media').count() == 0
                page.goto(base + '/m/2?recent=' + old_token)
                expect(page.locator('#reader-error')).to_contain_text('Не удалось открыть')
                assert page.locator('#v img').count() == 0
                page.goto(base + '/')
                expect(recent.get_by_role('button', name='Читалка: Манга')).to_be_visible()
                recent.get_by_role('button', name='Очистить историю открытий').click()
                expect(recent.locator('[role=status]')).to_contain_text('очищена')
                assert page.evaluate("localStorage.getItem('mediahub.recent.v1')") is None
                print('Edge: recent history, revalidation, guarded opening and clear passed')
            finally:
                browser.close()
    finally:
        server.shutdown(); server.server_close(); thread.join(); app.db.close()


if __name__ == '__main__':
    with tempfile.TemporaryDirectory() as folder:
        run(Path(folder))
