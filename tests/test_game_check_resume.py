"""Game check checkpoints and continuation, without network or user data."""
import threading
import unittest

from core import game_check


class ResumeTests(unittest.TestCase):
    def setUp(self):
        self.rows = {i: {'id': i, 'kind': 'game', 'url': f'game:{i}', 'title': f'Game {i}',
                         'thread': f'https://example.com/{i}', 'version': '1'} for i in range(1, 87)}
        self.seen = []
        self.jobs = {}

    def sql(self, query, args=()):
        if query == "select * from items where kind='game'": return list(self.rows.values())
        if query == 'select * from items where id=?': return [self.rows[args[0]]] if args[0] in self.rows else []
        raise AssertionError(query)

    def info(self, row): return {'meta': {'thread': row['thread'], 'version': row['version']}}
    def parse(self, html, url): return {'name': html, 'version': '1'}
    def apply(self, meta, thread): pass
    def run_job(self, job, fetch, online=lambda: True):
        game_check.run(job, online, self.sql, self.info, fetch, self.parse, self.apply, 0)
    def enqueue(self, url, kind, **kwargs):
        jid = len(self.jobs) + 1
        self.jobs[jid] = dict(id=jid, url=url, kind=kind, status='в очереди', cancel=False, **kwargs)
        return jid

    def test_86_cancel_and_resume_does_not_repeat_started_or_unknown(self):
        job = {'id': 1, 'kind': 'gamecheck', 'status': 'качается', 'cancel': False}
        self.jobs[1] = job
        def fetch(url, j):
            self.seen.append(url)
            if len(self.seen) == 2: raise RuntimeError('timeout')
            if len(self.seen) == 3: j['cancel'] = True
            return url
        self.run_job(job, fetch); job['status'] = 'отменено'
        snap = game_check.snapshot(job)
        self.assertEqual((snap['total'], snap['pending'], snap['ok'], snap['unknown'], snap['resume']), (86, 83, 2, 1, True))
        self.assertEqual(snap['errors'], [{'id': 2, 'title': 'Game 2', 'reason': 'timeout'}])
        result, status = game_check.resume({'resume': 1}, self.jobs, self.enqueue)
        self.assertEqual(status, 200)
        self.assertEqual(game_check.resume({'resume': 1}, self.jobs, self.enqueue)[1], 409)
        resumed = self.jobs[result['job']]
        self.run_job(resumed, lambda url, j: self.seen.append(url) or url)
        self.assertEqual(len(self.seen), 86)
        self.assertEqual(len(set(self.seen)), 86)
        self.assertEqual(game_check.snapshot(resumed)['ok'], 85)
        self.assertEqual(game_check.snapshot(resumed)['unknown'], 1)
        self.assertEqual(game_check.snapshot(resumed)['pending'], 0)
        self.assertTrue(resumed['final'].startswith('частично:'))
        self.assertEqual(game_check.snapshot(job)['pending'], 83)

    def test_offline_and_queued_cancel_can_resume_without_attempt(self):
        job = {'id': 1, 'kind': 'gamecheck', 'status': 'качается', 'cancel': False}
        self.jobs[1] = job
        with self.assertRaises(RuntimeError): self.run_job(job, lambda *a: self.fail('fetch'), online=lambda: False)
        job['status'] = 'ошибка: расширение'
        result, status = game_check.resume({'resume': 1}, self.jobs, self.enqueue)
        self.assertEqual(status, 200)
        resumed = self.jobs[result['job']]; resumed.update(status='отменено', cancel=True)
        self.assertEqual(game_check.snapshot(resumed)['pending'], 86)
        self.assertEqual(game_check.resume({'resume': resumed['id']}, self.jobs, self.enqueue)[1], 200)

    def test_changed_or_deleted_card_skipped_without_fetch(self):
        job = {'id': 1, 'kind': 'gamecheck', 'status': 'качается', 'cancel': False, 'ids': [1, 2, 3]}
        self.jobs[1] = job
        def fetch(url, j): j['cancel'] = True; self.seen.append(url); return url
        self.run_job(job, fetch); job['status'] = 'отменено'
        self.rows[2]['thread'] = 'https://example.com/changed'; del self.rows[3]
        result, _ = game_check.resume({'resume': 1}, self.jobs, self.enqueue)
        resumed = self.jobs[result['job']]
        self.run_job(resumed, lambda url, j: self.fail('changed card fetched'))
        self.assertEqual(game_check.snapshot(resumed)['skipped'], 2)
        self.assertEqual(self.seen, ['https://example.com/1'])

    def test_claim_is_atomic_across_tabs_and_rejects_active_or_bad_request(self):
        job = {'id': 1, 'kind': 'gamecheck', 'status': 'качается', 'cancel': False, 'ids': [1]}
        self.jobs[1] = job
        with self.assertRaises(RuntimeError): self.run_job(job, lambda *a: '', online=lambda: False)
        self.assertEqual(game_check.resume({'resume': 1}, self.jobs, self.enqueue)[1], 409)
        self.assertEqual(game_check.resume({'resume': True}, self.jobs, self.enqueue)[1], 400)
        job['status'] = 'ошибка'
        results = []
        threads = [threading.Thread(target=lambda: results.append(game_check.resume({'resume': 1}, self.jobs, self.enqueue)[1])) for _ in range(2)]
        for t in threads: t.start()
        for t in threads: t.join()
        self.assertEqual(sorted(results), [200, 409])

    def test_failure_after_network_is_unknown_and_not_repeated(self):
        job = {'id': 1, 'kind': 'gamecheck', 'status': 'качается', 'cancel': False, 'ids': [1, 2]}
        self.jobs[1] = job
        def broken(meta, thread):
            job['cancel'] = True
            raise RuntimeError('save outcome unknown')
        game_check.run(job, lambda: True, self.sql, self.info, lambda *args: 'page', self.parse, broken, 0)
        job['status'] = 'отменено'
        result, _ = game_check.resume({'resume': 1}, self.jobs, self.enqueue)
        self.run_job(self.jobs[result['job']], lambda url, j: self.seen.append(url) or url)
        self.assertEqual(self.seen, ['https://example.com/2'])
        self.assertEqual(game_check.snapshot(job)['unknown'], 1)
