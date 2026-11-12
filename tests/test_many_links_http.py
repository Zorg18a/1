"""Large pasted batches must reach the queue, including site page selections."""
import os
import subprocess
import sys
import tempfile
import unittest


class ManyLinksHttpTests(unittest.TestCase):
    def test_eighty_three_links_and_selected_pages(self):
        code = r'''
import http.client, json, threading
from core.local_http import LocalHTTPServer
from legacy import app
server = LocalHTTPServer(('127.0.0.1', 0), app.H)
t = threading.Thread(target=server.serve_forever); t.start()
def post(data):
    c = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
    try:
        c.request('POST', '/api/add', json.dumps(data), {'X-MH':'1'})
        r = c.getresponse(); return r.status, json.loads(r.read())
    finally: c.close()
urls = ['https://example.invalid/page-' + str(i) for i in range(83)]
try:
    for kind, selection in [('video', []), ('mangaurl', []), ('site', []), ('site', urls)]:
        app.jobs.clear()
        while not app.scheduler.pending.empty(): app.scheduler.pending.get_nowait()
        status, result = post({'kind':kind, 'urls':'\n'.join(urls), 'sel':selection})
        assert status == 200 and result['added'] == 83, (kind,status,result)
        queued = [app.scheduler.pending.get_nowait() for _ in range(83)]
        assert [j['url'] for j in queued] == urls
        assert len(app.jobs) == 83 and app.scheduler.pending.empty()
        assert queued[0]['sel'] == selection
        assert all(not j['sel'] for j in queued[1:])
        seen = []; app.scheduler.run_job = lambda j: seen.append(j['url'])
        for job in queued: app.scheduler.process(job)
        assert seen == urls and all(j['status'] == 'готово' for j in queued)
    app.jobs.clear()
    status, result = post({'kind':'video', 'urls':urls[0] + '\n' + urls[0] + '\n' + urls[1]})
    assert status == 200 and result['added'] == 2
finally:
    server.shutdown(); server.server_close(); t.join(); app.db.close()
'''
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, '-c', code], env=dict(os.environ, MEDIAHUB_DATA_DIR=directory),
                                    text=True, capture_output=True, timeout=40)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
