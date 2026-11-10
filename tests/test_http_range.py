"""Exercise real MediaHub HTTP range requests against temporary files and DB."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class HttpRangeTests(unittest.TestCase):
    def test_media_ranges_and_security(self):
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory)
            (data / 'video.mp4').write_bytes(b'0123456789')
            (data / 'empty.mp4').write_bytes(b'')
            code = r'''
import http.client, os, threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from legacy import app
root = Path(os.environ['MEDIAHUB_DATA_DIR'])
app.sql("insert into items(id,title,kind,path,url) values(1,'Video','video',?,'v'),(2,'Empty','video',?,'e')",
        (str(root / 'video.mp4'), str(root / 'empty.mp4')))
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
def check(path, headers, status, body, content_range=None):
    actual, response, data = request(path, headers)
    assert (actual, data) == (status, body), (headers, actual, data)
    assert response.get('Content-Length') == str(len(body)), response
    assert response.get('Accept-Ranges') == 'bytes', response
    assert response.get('Content-Range') == content_range, response
try:
    check('/f/1', {}, 200, b'0123456789')
    check('/f/1', {'Range':'bytes=2-5'}, 206, b'2345', 'bytes 2-5/10')
    check('/f/1', {'Range':'bytes=5-'}, 206, b'56789', 'bytes 5-9/10')
    check('/f/1', {'Range':'bytes=-3'}, 206, b'789', 'bytes 7-9/10')
    check('/f/1', {'Range':'bytes=-500'}, 206, b'0123456789', 'bytes 0-9/10')
    check('/f/1', {'Range':'bytes=10-'}, 416, b'', 'bytes */10')
    check('/f/1', {'Range':'bytes=-0'}, 416, b'', 'bytes */10')
    check('/f/1', {'Range':'bytes=1-2,4-5'}, 200, b'0123456789')
    check('/f/1', {'Range':'bytes=2-3', 'If-Range':'"other"'}, 200, b'0123456789')
    check('/f/1', {'Range':'bytes=' + '9' * 5000 + '-'}, 416, b'', 'bytes */10')
    check('/f/2', {}, 200, b'')
    check('/f/2', {'Range':'bytes=0-'}, 416, b'', 'bytes */0')
    conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
    try:
        conn.putrequest('GET', '/f/1'); conn.putheader('Range', 'bytes=0-1')
        conn.putheader('Range', 'bytes=2-3'); conn.endheaders()
        response = conn.getresponse()
        assert response.status == 200 and response.read() == b'0123456789'
    finally:
        conn.close()
    assert request('/f/999')[0] == 404
    assert request('/f/1', {'Host':'evil.example', 'Range':'bytes=0-1'})[0] == 403
    status, response, page = request('/ui/app.js')
    assert status == 200 and len(page) > 0 and int(response['Content-Length']) == len(page)
finally:
    server.shutdown(); server.server_close(); thread.join(); app.db.close()
'''
            subprocess.run([sys.executable, '-c', code], env=dict(os.environ, MEDIAHUB_DATA_DIR=directory),
                           check=True, timeout=30)
