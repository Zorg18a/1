"""Subtitle routes against a temporary library with no user files."""
import os
import subprocess
import sys
import tempfile
import unittest


class SubtitleHttpTests(unittest.TestCase):
    def test_discovery_conversion_and_access_controls(self):
        code = r'''
import http.client, json, os, threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from legacy import app
root = Path(os.environ['MEDIAHUB_DATA_DIR']).resolve()
movie = root / 'video.mp4'
movie.write_bytes(b'video')
(root / 'video.ru.srt').write_bytes('1\n00:00:01,000 --> 00:00:02,000\nПривет\n'.encode('cp1251'))
(root / 'video.en.vtt').write_bytes(b'WEBVTT\n\nEnglish\n')
app.sql("insert into items(id,title,kind,path,url) values(1,'Video','video',?,'v'),(2,'Game','game',?,'g')", (str(movie), str(movie)))
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
    status, _, body = request('/api/subtitles/1')
    tracks = json.loads(body)['subs']
    assert status == 200 and [track['lang'] for track in tracks] == ['en', 'ru'], (status, tracks)
    assert tracks[1]['url'].startswith('/sub/1/1.vtt?rev=')
    status, headers, body = request(tracks[1]['url'])
    assert status == 200 and headers['Content-Type'] == 'text/vtt; charset=utf-8'
    assert headers['X-Content-Type-Options'] == 'nosniff'
    assert int(headers['Content-Length']) == len(body)
    assert b'WEBVTT\n\n' in body and b'00:00:01.000 --> 00:00:02.000' in body
    assert 'Привет' in body.decode('utf8')
    (root / 'video.ru.srt').write_text('1\n00:00:03,000 --> 00:00:04,000\nНовый текст\n', encoding='utf8')
    assert request(tracks[1]['url'])[0] == 404  # stale discovery cannot silently select a different file
    assert request('/sub/1/1.vtt')[0] == 200
    assert request('/sub/1/1.vtt?rev=bad')[0] == 404
    assert request('/sub/1/2.vtt')[0] == 404
    assert request('/sub/2/0.vtt')[0] == 404
    assert request('/api/subtitles/999')[0] == 404
    assert request('/api/subtitles/9223372036854775808')[0] == 404
    assert request('/sub/1/../../video.ru.srt')[0] == 404
    assert request('/sub/1/0.vtt', {'Host':'evil.example'})[0] == 403
finally:
    server.shutdown(); server.server_close(); thread.join(); app.db.close()
'''
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run([sys.executable, '-c', code], env=dict(os.environ, MEDIAHUB_DATA_DIR=directory),
                           check=True, timeout=30)
