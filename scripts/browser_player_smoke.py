"""Headless Edge player smoke against temporary local media and database.

Requires Playwright and an installed Microsoft Edge; no real user data or network.
"""
import os
from pathlib import Path
import tempfile
import threading
import traceback
import wave
from http.server import ThreadingHTTPServer

def run(root):
    from playwright.sync_api import expect, sync_playwright

    os.environ['MEDIAHUB_DATA_DIR'] = str(root)
    from legacy import app

    app.cfg['folder'] = str(root / 'downloads')
    media = root / 'sample.wav'
    with wave.open(str(media), 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(bytes(8000 * 2 * 3))
    (root / 'sample.en.srt').write_text(
        '1\n00:00:00,000 --> 00:00:02,000\nHello from subtitles\n', encoding='utf8')
    app.sql("insert into items(id,title,author,topic,kind,path,url) "
            "values(1,'Видео','','','video',?,'test'),(2,'Игра','','','game','','game:test')", (str(media),))
    server = ThreadingHTTPServer(('127.0.0.1', 0), app.H)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel='msedge', headless=True)
            try:
                page = browser.new_page(viewport={'width': 320, 'height': 800})
                page.goto(f'http://127.0.0.1:{server.server_port}/', wait_until='domcontentloaded')
                expect(page.locator('.grid.wide .c').first).to_be_visible()
                for name in ('Библиотека', 'Входящие', 'Загрузки', 'Игры', 'Настройки'):
                    expect(page.get_by_role('navigation').get_by_role('link', name=name)).to_be_visible()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'), 'Library overflows 320px'
                games = page.get_by_role('navigation').get_by_role('link', name='Игры')
                games.focus(); page.keyboard.press('Enter')
                expect(page.locator('#v-games')).to_be_visible()
                expect(page.locator('.gcard')).to_be_visible()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'), 'Games overflow 320px'
                page.locator('.gcard').focus(); page.keyboard.press('Enter')
                expect(page.locator('#gpanel')).to_have_attribute('aria-hidden', 'false')
                page.wait_for_function("""() => { const r = document.querySelector('#gpanel').getBoundingClientRect();
                    return r.left >= 0 && r.right <= innerWidth + 1; }""")
                page.locator('#gclose').click()
                page.get_by_role('navigation').get_by_role('link', name='Библиотека').click()
                page.get_by_role('link', name='Предпросмотр плеера без сохранения позиции: Видео').click()
                expect(page.locator('#player-title')).to_have_text('Видео')
                expect(page.locator('.notice')).to_contain_text('позиция воспроизведения пока не сохраняется')
                selector = page.get_by_label('Субтитры')
                expect(selector).to_be_visible()
                expect(selector).to_have_value('-1')
                selector.select_option('0')
                page.wait_for_function("document.querySelector('track')?.readyState === 2")
                assert page.locator('track').evaluate("t => t.track.cues[0].text") == 'Hello from subtitles'
                assert page.locator('video').evaluate("v => v.textTracks[0].mode") == 'showing'
                page.locator('video').evaluate('async v => { v.muted = true; await v.play(); }')
                page.wait_for_function("document.querySelector('video').currentTime > 0.1")
                page.locator('video').evaluate('v => { v.pause(); v.currentTime = 1.5; }')
                page.wait_for_function("Math.abs(document.querySelector('video').currentTime - 1.5) < 0.1")
                page.reload()
                expect(page.get_by_label('Субтитры')).to_have_value('0')
                page.evaluate('document.activeElement.blur()')
                page.keyboard.press('c')
                expect(page.get_by_label('Субтитры')).to_have_value('-1')
                page.reload()
                expect(page.get_by_label('Субтитры')).to_have_value('-1')
                assert page.locator('video').evaluate('v => v.paused && !v.autoplay')
                print('Edge: library → player, playback/seek, subtitles, persistence and C passed')
                app.jobs[91] = {'id': 91, 'url': 'test', 'kind': 'video', 'status': 'в очереди',
                                'title': 'Тест', 'cancel': False, 'pct': 0, 'speed': 0}
                page.goto(f'http://127.0.0.1:{server.server_port}/#downloads', wait_until='domcontentloaded')
                expect(page.locator('#v-downloads')).to_be_visible()
                expect(page.locator('#jobs')).to_contain_text('Тест')
                with page.expect_event('dialog') as event:
                    page.locator('#cxl').click()
                dialog = event.value
                assert 'заданий: 1' in dialog.message
                dialog.dismiss()
                expect(page.locator('#cxl')).to_be_enabled()
                assert not app.jobs[91]['cancel']
                with page.expect_event('dialog') as event:
                    page.locator('#cxl').click()
                event.value.accept()
                page.wait_for_function("document.querySelector('#toastBox').textContent.includes('Отмена запрошена')")
                assert app.jobs[91]['cancel'] and app.jobs[91]['status'] == 'отменено'
                expect(page.locator('#cxl')).to_be_focused()
                print('Edge: cancel confirmation, refusal and confirmed cancellation passed')
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
        app.db.close()


if __name__ == '__main__':
    try:
        with tempfile.TemporaryDirectory() as directory:
            run(Path(directory).resolve())
    except Exception:
        if os.environ.get('GITHUB_ACTIONS'):
            text = traceback.format_exc()[-6000:].replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A')
            print(f'::error title=Headless Edge smoke failed::{text}', flush=True)
        raise
