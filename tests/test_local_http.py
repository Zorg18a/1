"""Local server capacity without changing the application's loopback binding."""
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import unittest

from core.local_http import LocalHTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'ok')

    def log_message(self, *args):
        pass


class LocalHttpTests(unittest.TestCase):
    def test_backlog_and_loopback_server(self):
        self.assertTrue(issubclass(LocalHTTPServer, ThreadingHTTPServer))
        self.assertGreaterEqual(LocalHTTPServer.request_queue_size, 128)
        server = LocalHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever); thread.start()
        try:
            self.assertEqual(server.server_address[0], '127.0.0.1')
            conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
            try:
                conn.request('GET', '/')
                response = conn.getresponse()
                self.assertEqual((response.status, response.read()), (200, b'ok'))
            finally:
                conn.close()
        finally:
            server.shutdown(); server.server_close(); thread.join()
