import http.client
import json
import os
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

# The application creates its database on import; keep tests away from user data.
_tmp = tempfile.TemporaryDirectory()
os.environ['MEDIAHUB_DATA_DIR'] = _tmp.name
from legacy import app

# Refuse destructive test setup if another importer initialized real user data.
if app.BASE.resolve() != Path(_tmp.name).resolve():
    raise RuntimeError('MediaHub was imported before test isolation was established')


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
        app.db.close()
        _tmp.cleanup()

    def setUp(self):
        app.sql('delete from items')
        app.sql('delete from inbox')
        app.jobs.clear()
        app.PAIR.clear()
        app.EXT.clear()

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

    def post_json(self, path, data, headers=None):
        headers = dict(headers or {})
        headers['Content-Type'] = 'application/json'
        status, body = self.request('POST', path, json.dumps(data), headers)
        return status, json.loads(body)

    def pair_extension(self):
        origin = 'chrome-extension://test'
        ext_headers = {'Origin': origin}
        status, result = self.post_json('/ext/hello', {'name': 'Test'}, ext_headers)
        self.assertEqual((status, result['status']), (200, 'pending'))
        status, result = self.post_json('/api/ext/approve', {'origin': origin, 'allow': True},
                                        {'X-MH': '1'})
        self.assertEqual((status, result['ok']), (200, 1))
        status, result = self.post_json('/ext/hello', {'name': 'Test'}, ext_headers)
        self.assertEqual((status, result['status']), (200, 'ok'))
        ext_headers['X-MH-Token'] = result['token']
        return ext_headers

    def test_host_origin_and_extension_authentication(self):
        self.assertEqual(self.request('GET', '/', headers={'Host': 'evil.example'})[0], 403)
        self.assertEqual(self.request('POST', '/api/scan', '{}')[0], 403)
        self.assertEqual(self.request('POST', '/api/scan', '{}',
                                      {'X-MH': '1', 'Origin': 'https://evil.example'})[0], 403)
        self.assertEqual(self.request('GET', '/ext/ping')[0], 401)
        self.assertEqual(self.post_json('/ext/tabs', {'tabs': []})[0], 401)
        headers = self.pair_extension()
        self.assertEqual(self.request('GET', '/ext/ping', headers=headers)[0], 200)
        headers['X-MH-Token'] = 'invalid'
        self.assertEqual(self.request('GET', '/ext/ping', headers=headers)[0], 401)

    def test_inbox_duplicate_and_skip_do_not_close(self):
        headers = self.pair_extension()
        tabs = [{'id': 1, 'url': 'https://youtu.be/abc', 'title': 'First'},
                {'id': 2, 'url': 'https://www.youtube.com/watch?v=abc', 'title': 'Duplicate'},
                {'id': 3, 'url': 'file:///private', 'title': 'Invalid'}]
        status, result = self.post_json('/ext/tabs', {'tabs': tabs, 'close': True}, headers)
        self.assertEqual((status, result['count']), (200, 2))
        batch = result['batch']
        rows = app.sql('select * from inbox where batch=? order by id', (batch,))
        self.assertEqual((rows[0]['state'], rows[1]['state'], rows[1]['action']),
                         ('new', 'dup', 'skip'))
        data = {'batch': batch, 'close': True,
                'rows': [{'id': row['id'], 'action': 'skip'} for row in rows]}
        status, result = self.post_json('/api/inbox/confirm', data, {'X-MH': '1'})
        self.assertEqual((status, result['download']), (200, 0))
        self.assertTrue(all(row['status'] == 'skipped' and row['cmd'] == ''
                            for row in app.sql('select * from inbox where batch=?', (batch,))))

    def test_inbox_waits_for_success_and_acknowledgement(self):
        headers = self.pair_extension()
        _, result = self.post_json('/ext/tabs', {'tabs': [{'id': 42, 'url': 'https://youtu.be/abc'}],
                                                 'close': True}, headers)
        batch = result['batch']
        row = app.sql('select * from inbox where batch=?', (batch,))[0]
        _, result = self.post_json('/api/inbox/confirm',
                                   {'batch': batch, 'close': True,
                                    'rows': [{'id': row['id'], 'action': 'download'}]}, {'X-MH': '1'})
        self.assertEqual(result['download'], 1)
        row = app.sql('select * from inbox where id=?', (row['id'],))[0]
        job_id = json.loads(row['jobs'])[0]
        app.settle()
        self.assertEqual(app.sql('select status,cmd from inbox where id=?', (row['id'],))[0]['status'], 'queued')
        app.jobs[job_id]['status'] = 'готово'
        app.settle()
        updated = app.sql('select status,cmd from inbox where id=?', (row['id'],))[0]
        self.assertEqual((updated['status'], updated['cmd']), ('closing', 'close'))
        status, body = self.request('GET', '/ext/commands', headers=headers)
        self.assertEqual((status, json.loads(body)['commands'][0]['tab_id']), (200, 42))
        self.post_json('/ext/ack', {'id': row['id'], 'result': 'closed'}, headers)
        updated = app.sql('select status,cmd from inbox where id=?', (row['id'],))[0]
        self.assertEqual((updated['status'], updated['cmd']), ('closed', ''))

    def test_failed_or_cancelled_download_keeps_tab_open(self):
        for job_status in ('ошибка: timeout', 'отменено', 'частично: 1 из 2'):
            with self.subTest(status=job_status):
                batch, _ = app.inbox_add([{'id': 42, 'url': 'https://youtu.be/' + str(len(app.jobs))}], True, 'test')
                row = app.sql('select * from inbox where batch=?', (batch,))[0]
                app.inbox_confirm({'batch': batch, 'close': True,
                                   'rows': [{'id': row['id'], 'action': 'download'}]})
                queued = app.sql('select * from inbox where id=?', (row['id'],))[0]
                app.jobs[json.loads(queued['jobs'])[0]]['status'] = job_status
                app.settle()
                result = app.sql('select status,cmd,reason from inbox where id=?', (row['id'],))[0]
                self.assertEqual((result['status'], result['cmd']), ('kept', ''))
                self.assertTrue(result['reason'])

    def test_api_cancel_updates_queued_job(self):
        status, body = self.post_json('/api/add', {'urls': 'https://youtu.be/queued', 'kind': 'video'},
                                      {'X-MH': '1'})
        self.assertEqual((status, body['added']), (200, 1))
        job = next(iter(app.jobs.values()))
        self.assertEqual(job['status'], 'в очереди')
        status, _ = self.post_json('/api/cancel', {'id': job['id']}, {'X-MH': '1'})
        self.assertEqual(status, 200)
        self.assertTrue(job['cancel'])
        self.assertEqual(job['status'], 'отменено')
        self.assertEqual(self.post_json('/api/clear', {}, {'X-MH': '1'})[0], 200)
        self.assertNotIn(job['id'], app.jobs)

    def test_restart_only_closes_tab_if_downloaded_file_exists(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / 'video.mp4'
            file.write_bytes(b'video')
            for exists in (True, False):
                with self.subTest(exists=exists):
                    url = 'https://youtu.be/' + str(exists)
                    batch, _ = app.inbox_add([{'url': url}], True, 'test')
                    row = app.sql('select * from inbox where batch=?', (batch,))[0]
                    app.inbox_confirm({'batch': batch, 'close': True,
                                       'rows': [{'id': row['id'], 'action': 'download'}]})
                    path = file if exists else Path(directory) / 'missing.mp4'
                    app.sql("update items set kind='video', path=? where url=?",
                            (str(path), app.classify(url)['key']))
                    app.jobs.clear()  # Simulates a restart losing in-memory jobs.
                    app.settle()
                    row = app.sql('select status,cmd from inbox where id=?', (row['id'],))[0]
                    self.assertEqual((row['status'], row['cmd']),
                                     ('closing', 'close') if exists else ('kept', ''))

    def test_game_check_accepts_specific_id(self):
        status, result = self.post_json('/api/game/check', {'id': 17}, {'X-MH': '1'})
        self.assertEqual(status, 200)
        self.assertEqual(app.jobs[result['job']]['ids'], [17])
