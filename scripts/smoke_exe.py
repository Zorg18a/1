"""Exercise the packaged Windows application without accessing user data."""
import http.client
import json
import os
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
    assert get(8765, '/', 'example.invalid')[0] == 403
    assert get(8765, '/m/1')[0] == 200
    status, body = get(8765, '/api/library')
    assert status == 200 and json.loads(body) == []
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
