"""Exercise the packaged Windows application without accessing user data."""
import http.client
import json
import os
import sqlite3
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlparse


def get(port, path, host=None):
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
    try:
        connection.request('GET', path, headers={'Host': host} if host else {})
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()


def post(path, data):
    connection = http.client.HTTPConnection('127.0.0.1', 8765, timeout=5)
    try:
        connection.request('POST', path, json.dumps(data), {'X-MH': '1', 'Content-Type': 'application/json'})
        response = connection.getresponse()
        return response.status, json.loads(response.read())
    finally:
        connection.close()


def check(process):
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f'MediaHub exited early: {process.returncode}')
        try:
            status, html = get(8765, '/')
            if status == 200 and b'MediaHub' in html:
                break
        except OSError:
            pass
        time.sleep(0.5)
    else:
        raise RuntimeError('MediaHub did not start on port 8765')
    assert 'Предпросмотр плеера'.encode('utf-8') in html
    assert get(8765, '/', 'example.invalid')[0] == 403
    status, reader = get(8765, '/m/1')
    assert status == 200 and b'reader-conflict-check' in reader
    status, body = get(8765, '/mi/1/12/001.png?identity=bad')
    assert status == 400 and json.loads(body)['error']
    assert get(8765, '/ui/app.js')[0] == 200
    assert get(8765, '/ui/backup.js')[0] == 200
    assert get(8765, '/ui/game-library.js')[0] == 200
    assert get(8765, '/ui/game-tags.js')[0] == 200
    assert get(8765, '/ui/game-update-preview.js')[0] == 200
    assert get(8765, '/ui/save-inventory.js')[0] == 200
    assert get(8765, '/ui/accessibility.css')[0] == 200
    assert get(8765, '/ui/reader.js')[0] == 200
    status, reader_progress = get(8765, '/ui/reader-progress.js')
    assert status == 200 and b'setupProgressConflict' in reader_progress
    assert get(8765, '/ui/reader-modes.js')[0] == 200
    assert get(8765, '/ui/reader.css')[0] == 200
    assert get(8765, '/p/1')[0] == 200
    assert get(8765, '/ui/player.js')[0] == 200
    assert get(8765, '/ui/player-keys.js')[0] == 200
    assert get(8765, '/ui/player-subtitles.js')[0] == 200
    assert get(8765, '/ui/player-progress.js')[0] == 200
    assert get(8765, '/ui/player.css')[0] == 200
    status, body = get(8765, '/api/library')
    assert status == 200 and json.loads(body) == []
    connection = http.client.HTTPConnection('127.0.0.1', 8765, timeout=30)
    try:
        connection.request('POST', '/api/backup', headers={'X-MH': '1'})
        response = connection.getresponse(); data = response.read()
        assert response.status == 200 and response.getheader('Content-Type') == 'application/vnd.sqlite3'
    finally:
        connection.close()
    copy = sqlite3.connect(':memory:')
    try:
        copy.deserialize(data)
        assert copy.execute('pragma integrity_check').fetchone()[0] == 'ok'
        assert copy.execute('select count(*) from items').fetchone()[0] == 0
    finally:
        copy.close()
    connection = http.client.HTTPConnection('127.0.0.1', 8765, timeout=30)
    try:
        connection.request('POST', '/api/backup/inspect', body=data,
                           headers={'X-MH': '1', 'Content-Type': 'application/octet-stream'})
        response = connection.getresponse(); inspected = json.loads(response.read())
        assert response.status == 200 and inspected == {'ok': 1, 'items': 0, 'progress': 0}
    finally:
        connection.close()
    status, body = get(8765, '/api/subtitles/999')
    assert status == 404 and 'error' in json.loads(body)
    status, body = get(8765, '/api/player-preview/999')
    assert status == 404 and 'error' in json.loads(body)
    status, result = post('/api/add', {'urls': 'https://example.invalid/test', 'kind': 'video',
                                       'start_at': time.time() + 3600})
    assert status == 200 and result['added'] == 1
    status, body = get(8765, '/api/jobs')
    jobs = json.loads(body)
    assert status == 200 and len(jobs) == 1 and jobs[0]['status'].startswith('запланировано')
    assert post('/api/cancel', {'id': jobs[0]['id']})[0] == 200
    status, body = get(8765, '/api/ext')
    info = json.loads(body)
    assert status == 200 and Path(info['ext_dir'], 'manifest.json').is_file()
    assert Path(info['ext_ff']).is_file()
    status, body = get(8765, '/api/games')
    game_url = urlparse(json.loads(body)['url'])
    assert status == 200 and game_url.hostname == '127.0.0.1'
    status, body = get(game_url.port, '/?' + game_url.query)
    assert status == 200 and b'GameSweep' in body


def main():
    executable = Path(sys.argv[1]).resolve()
    with tempfile.TemporaryDirectory() as directory:
        data = Path(directory)
        (data / 'settings.json').write_text(json.dumps({'folder': str(data / 'downloads')}))
        env = dict(os.environ, MEDIAHUB_DATA_DIR=str(data), MEDIAHUB_NO_BROWSER='1')
        process = subprocess.Popen([str(executable)], env=env, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL)
        try:
            check(process)
            print('Packaged MediaHub and GameSweep smoke test passed')
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == '__main__':
    main()
