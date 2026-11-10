"""Player preview routes with a temporary local library and media."""
import os
import subprocess
import sys
import tempfile
import unittest


class PlayerPreviewHttpTests(unittest.TestCase):
    def test_preview_metadata_and_reader_compatibility(self):
        code = r'''
import http.client, json, os, threading, wave
from http.server import ThreadingHTTPServer
from pathlib import Path
from legacy import app
root = Path(os.environ['MEDIAHUB_DATA_DIR']).resolve()
media = root / 'sample.wav'
with wave.open(str(media), 'wb') as file:
    file.setnchannels(1); file.setsampwidth(2); file.setframerate(8000); file.writeframes(bytes(16000))
(root / 'sample.en.srt').write_text('1\n00:00:00,000 --> 00:00:01,000\nTest\n', encoding='utf8')
app.sql("insert into items(id,title,author,topic,kind,path,url) values(1,'<Title>','','','audio',?,'a'),(2,'Video','','','video',?,'v'),(3,'Game','','','game',?,'g'),(4,'Missing','','','audio','relative.wav','m')", (str(media), str(media), str(media)))
server = ThreadingHTTPServer(('127.0.0.1', 0), app.H)
thread = threading.Thread(target=server.serve_forever)
thread.start()
def request(path, headers=None):
    conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
    try:
        conn.request('GET', path, headers=headers or {})
        response = conn.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        conn.close()
try:
    status, _, page = request('/p/1')
    assert status == 200 and b'/ui/player.js' in page and 'позиция воспроизведения пока не сохраняется' in page.decode('utf8')
    assert 'for="player-subtitles"' in page.decode('utf8')
    status, _, body = request('/api/player-preview/1')
    item = json.loads(body)
    assert status == 200 and item['title'] == '<Title>' and item['kind'] == 'audio'
    assert item['src'] == '/f/1' and item['position_available'] is False
    assert len(item['subs']) == 1 and item['subs'][0]['lang'] == 'en'
    assert str(root) not in body.decode('utf8')
    status, headers, body = request(item['subs'][0]['url'])
    assert status == 200 and headers['Content-Type'].startswith('text/vtt') and b'00:00:00.000' in body
    status, headers, body = request(item['src'], {'Range':'bytes=0-3'})
    assert status == 206 and body == b'RIFF' and headers['Content-Range'].startswith('bytes 0-3/')
    assert json.loads(request('/api/player-preview/2')[2])['kind'] == 'video'
    assert json.loads(request('/api/player-preview/4')[2])['subtitle_warning'] is True
    assert request('/api/player-preview/3')[0] == 404
    assert request('/api/player-preview/9223372036854775808')[0] == 404
    assert request('/api/player-preview/1', {'Host':'evil.example'})[0] == 403
    status, _, body = request('/api/library')
    assert status == 200 and next(row for row in json.loads(body) if row['id'] == 1)['open'] == '/f/1'
    assert request('/m/1')[0] == 200
finally:
    server.shutdown(); server.server_close(); thread.join(); app.db.close()
'''
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run([sys.executable, '-c', code], env=dict(os.environ, MEDIAHUB_DATA_DIR=directory),
                           check=True, timeout=30)
