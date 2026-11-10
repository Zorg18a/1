import threading
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from storage.cover_download import download_cover


class CoverDownloadTests(unittest.TestCase):
    def test_redirects_are_guarded_before_request_and_download_is_bounded(self):
        visited = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                visited.append(self.path)
                if self.path == '/redirect':
                    self.send_response(302)
                    self.send_header('Location', '/blocked')
                    self.end_headers()
                else:
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b'0123456789')

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            root = f'http://127.0.0.1:{server.server_port}'
            seen = []

            def guard(url):
                seen.append(url)
                if url.endswith('/blocked'):
                    raise ValueError('blocked')

            with self.assertRaises(ValueError):
                download_cover(root + '/redirect', root, guard, urllib.request.build_opener(), 4)
            self.assertEqual(visited, ['/redirect'])
            self.assertTrue(seen[-1].endswith('/blocked'))
            self.assertEqual(download_cover(root + '/image', root, guard, urllib.request.build_opener(), 4), b'01234')
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
