"""Headless Edge player smoke against temporary local media and database.

Requires Playwright and an installed Microsoft Edge; no real user data or network.
"""
import json
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
    game_folder = root / 'game'
    game_folder.mkdir()
    game_info = {'update': True, 'inst': {'version': '1'},
                 'meta': {'version': '2', 'thread': 'https://example.org/thread', 'links': []}}
    app.sql('update items set path=?,info=? where id=2', (str(game_folder), json.dumps(game_info)))
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
                expect(page.locator('#v-library .tools [role="status"]')).to_have_count(1)
                page.locator('#so').select_option('title')
                page.locator('#gb').select_option('topic')
                video_chip = page.locator('#chips button[onclick="setK(\'video\')"]')
                video_chip.click()
                page.reload()
                expect(page.locator('#so')).to_have_value('title')
                expect(page.locator('#gb')).to_have_value('topic')
                expect(video_chip).to_have_attribute('aria-pressed', 'true')
                page.locator('#q').fill('нет такого материала')
                expect(page.locator('#lib')).to_contain_text('выбранному типу')
                expect(video_chip).to_have_attribute('aria-pressed', 'true')
                page.locator('#q').fill('')
                preview = page.get_by_role('link', name='Предпросмотр плеера: Видео')
                expect(preview).to_be_visible()
                hint = page.locator('#library-playback-hint')
                expect(hint).to_contain_text('не использует позицию предпросмотра')
                expect(hint).to_contain_text('только в этом браузере')
                card = page.locator('.c').filter(has=page.locator('a[href="/p/1"]'))
                cover = card.get_by_role('link', name='Открыть файл напрямую: Видео')
                expect(cover).to_have_attribute('href', '/f/1')
                expect(cover).to_have_attribute('target', '_blank')
                expect(cover).to_have_attribute('aria-describedby', 'library-playback-hint')
                expect(preview).to_have_attribute('aria-describedby', 'library-playback-hint')
                cover.focus(); expect(cover).to_be_focused()
                page.locator('#so').select_option('size')
                expect(page.get_by_role('link', name='Открыть файл напрямую: Видео')).to_have_attribute('href', '/f/1')
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
                card.hover()
                card.get_by_role('button', name='Удалить').click()
                expect(page.locator('#delDlg')).to_be_visible()
                expect(page.locator('#delT')).to_contain_text(str(media))
                expect(page.locator('#delT')).to_contain_text('без Корзины')
                expect(page.locator('#delC')).to_be_focused()
                page.locator('#delC').click()
                assert media.is_file() and app.sql('select id from items where id=1')
                games = page.get_by_role('navigation').get_by_role('link', name='Игры')
                games.focus(); page.keyboard.press('Enter')
                expect(page.locator('#v-games')).to_be_visible()
                expect(page.locator('#gsort-hint')).to_contain_text('всегда показаны первыми')
                expect(page.locator('.gcard')).to_be_visible()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'), 'Games overflow 320px'
                page.locator('.gcard').focus(); page.keyboard.press('Enter')
                expect(page.locator('#gpanel')).to_have_attribute('aria-hidden', 'false')
                expect(page.locator('#gpanel [data-ga="thread"]')).to_have_text('Открыть страницу обновления')
                expect(page.locator('#gpanel .update-preview')).to_contain_text('Архив не устанавливается')
                assert page.locator('#gpanel').evaluate('e => e.scrollWidth <= e.clientWidth + 1'), 'Game panel content overflows'
                page.wait_for_function("""() => { const r = document.querySelector('#gpanel').getBoundingClientRect();
                    return r.left >= 0 && r.right <= innerWidth + 1; }""")
                page.locator('#gpanel [data-ga="drop"]').click()
                expect(page.locator('#delDlg')).to_be_visible()
                expect(page.locator('#delT')).to_contain_text('Теги и заметки')
                expect(page.locator('#delF')).to_be_hidden()
                page.locator('#delC').click()
                assert game_folder.is_dir() and app.sql('select id from items where id=2')
                expect(page.locator('#gpanel')).to_have_attribute('aria-hidden', 'false')
                page.locator('#gclose').click()
                page.get_by_role('navigation').get_by_role('link', name='Библиотека').click()
                page.get_by_role('link', name='Предпросмотр плеера: Видео').click()
                expect(page.locator('#player-title')).to_have_text('Видео')
                expect(page.locator('.notice')).to_contain_text('позиция сохраняется в этом браузере')
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
                page.wait_for_function("Math.abs(JSON.parse(localStorage.getItem('mediahub.player.position.v1.1') || '{}').position - 1.5) < 0.1")
                page.reload()
                page.wait_for_function("Math.abs(document.querySelector('video')?.currentTime - 1.5) < 0.1")
                assert page.locator('video').evaluate('v => v.paused && !v.autoplay')
                expect(page.locator('#player-progress-status')).to_contain_text('восстановлена')
                page.get_by_role('button', name='С начала').click()
                page.wait_for_function("document.querySelector('video')?.currentTime < 0.1")
                assert page.evaluate("localStorage.getItem('mediahub.player.position.v1.1')") is None
                page.reload()
                page.wait_for_function("document.querySelector('video')?.readyState >= 1")
                assert page.locator('video').evaluate('v => v.currentTime < 0.1 && v.paused')
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
                batch, _ = app.inbox_add([{'id': 10, 'url': 'https://example.org/game'},
                                          {'id': 11, 'url': 'https://example.org/list'}], False, 'test')
                rows = app.sql('select id from inbox where batch=? order by id', (batch,))
                app.sql("update inbox set kind='game',action='gamecard' where id=?", (rows[0]['id'],))
                app.sql("update inbox set kind='playlist',action='track' where id=?", (rows[1]['id'],))
                page.goto(f'http://127.0.0.1:{server.server_port}/#inbox', wait_until='domcontentloaded')
                expect(page.locator('#inb .batch')).to_have_count(1)
                expect(page.locator('#inb')).to_contain_text('Вкладка останется открытой')
                page.get_by_role('button', name='Только сохранить ссылки').click()
                expect(page.locator('#ibStatus')).to_contain_text('Закрытие вкладок не запрошено')
                expect(page.locator('#ibStatus')).to_contain_text('отслеживание не отключается')
                assert len(app.jobs) == 1
                assert all(r['status'] == 'done' for r in app.sql('select status from inbox where batch=?', (batch,)))
                assert all(not r['tracked'] for r in app.sql("select tracked from items where src like 'https://example.org/%'"))
                app.inbox_add([{'id': 12, 'url': 'https://example.org/failure'}], False, 'test')
                page.reload()
                expect(page.get_by_role('button', name='Только сохранить ссылки')).to_be_visible()
                page.route('**/api/inbox/confirm', lambda route: route.abort())
                page.get_by_role('button', name='Только сохранить ссылки').click()
                expect(page.locator('#ibStatus')).to_contain_text('Некоторые строки могли уже обработаться')
                expect(page.get_by_role('button', name='Только сохранить ссылки')).to_be_enabled()
                print('Edge: inbox links-only, close opt-in and uncertain network result passed')
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
