import http.client
import json
import os
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer

# The application creates its database on import; keep tests away from user data.
_tmp = tempfile.TemporaryDirectory()
os.environ['MEDIAHUB_DATA_DIR'] = _tmp.name
from legacy import app


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), app.H)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        app.sql('delete from items')
        app.sql('delete from inbox')

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port)
        connection.request(method, path, body, headers or {})
        response = connection.getresponse()
        result = response.status, response.read()
        connection.close()
        return result

    def test_ui_and_empty_library(self):
        status, page = self.request('GET', '/')
        self.assertEqual(status, 200)
        self.assertIn(b'MediaHub', page)
        status, data = self.request('GET', '/api/library')
        self.assertEqual((status, json.loads(data)), (200, []))

    def test_security_and_save_link(self):
        self.assertEqual(self.request('GET', '/', headers={'Host': 'evil.example'})[0], 403)
        self.assertEqual(self.request('POST', '/api/scan', '{}')[0], 403)
        batch, count = app.inbox_add([{'url': 'https://example.org/page', 'title': 'Example'}], False, 'test')
        self.assertEqual(count, 1)
        row = app.sql('select id from inbox where batch=?', (batch,))[0]
        body = json.dumps({'batch': batch, 'rows': [{'id': row['id'], 'action': 'link'}]})
        status, data = self.request('POST', '/api/inbox/confirm', body, {'X-MH': '1'})
        self.assertEqual((status, json.loads(data)['links']), (200, 1))
        self.assertEqual(app.sql('select title from items')[0]['title'], 'Example')
