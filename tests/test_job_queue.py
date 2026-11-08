import itertools
import threading
import unittest
from unittest.mock import Mock, patch

from core.job_queue import JobQueue


def job(**overrides):
    data = {'id': 1, 'start_at': 0, 'status': 'в очереди', 'cancel': False,
            'daily': False, 'pct': 0, 'speed': 3, 'kind': 'video'}
    data.update(overrides)
    return data


class JobQueueTests(unittest.TestCase):
    def setUp(self):
        self.run_job = Mock()
        self.scheduler = JobQueue({}, itertools.count(2), self.run_job)

    def test_enqueue_and_process_immediate_job(self):
        item = job()
        self.scheduler.enqueue(item)
        self.assertIs(self.scheduler.jobs[1], item)
        self.assertIs(self.scheduler.pending.get_nowait(), item)
        self.scheduler.process(item)
        self.run_job.assert_called_once_with(item)
        self.assertEqual((item['status'], item['pct'], item['speed']), ('готово', 100, 0))

    @patch('core.job_queue.threading.Timer')
    @patch('core.job_queue.time.time', return_value=1000)
    def test_scheduled_job_and_daily_rescheduling(self, clock, timer):
        item = job(start_at=1100, daily=True)
        self.scheduler.enqueue(item)
        self.assertTrue(item['status'].startswith('запланировано'))
        self.assertTrue(self.scheduler.pending.empty())
        self.assertEqual(timer.call_args.args[0], 100)
        self.assertTrue(timer.return_value.daemon)
        timer.return_value.start.assert_called_once()
        self.scheduler.fire(item)
        self.assertIs(self.scheduler.pending.get_nowait(), item)
        self.assertEqual(item['status'], 'в очереди')
        following = self.scheduler.jobs[2]
        self.assertEqual((following['start_at'], following['daily'], following['pct']), (87500, True, 0))
        self.assertTrue(following['status'].startswith('запланировано'))
        self.assertEqual(timer.call_count, 2)

    @patch('core.job_queue.threading.Timer')
    @patch('core.job_queue.time.time', return_value=1000)
    def test_cancelled_scheduled_job_does_not_fire_or_repeat(self, clock, timer):
        item = job(start_at=1100, daily=True)
        self.scheduler.enqueue(item)
        item['cancel'] = True
        self.scheduler.fire(item)
        self.assertTrue(self.scheduler.pending.empty())
        self.assertEqual(len(self.scheduler.jobs), 1)
        self.assertEqual(timer.call_count, 1)

    def test_cancelled_queued_job_does_not_run(self):
        item = job(cancel=True)
        self.scheduler.process(item)
        self.run_job.assert_not_called()
        self.assertEqual(item['status'], 'отменено')

    def test_job_failure_and_final_status(self):
        self.run_job.side_effect = RuntimeError('failed')
        failed = job()
        self.scheduler.process(failed)
        self.assertEqual((failed['status'], failed['speed']), ('ошибка: failed', 0))
        self.run_job.side_effect = lambda item: item.update(final='частично')
        partial = job()
        self.scheduler.process(partial)
        self.assertEqual((partial['status'], partial['pct']), ('частично', 100))

    def test_cancellation_during_processing(self):
        self.run_job.side_effect = lambda item: item.update(cancel=True)
        item = job()
        self.scheduler.process(item)
        self.assertEqual(item['status'], 'отменено')

    @patch('core.job_queue.threading.Thread')
    def test_workers_only_increase(self, thread):
        self.scheduler.spawn_workers(2)
        self.scheduler.spawn_workers(1)
        self.scheduler.spawn_workers(3)
        self.assertEqual(thread.call_count, 3)
        self.assertEqual(thread.return_value.start.call_count, 3)
        self.assertEqual(self.scheduler.worker_count, 3)

    def test_real_worker_consumes_queue(self):
        finished = threading.Event()
        process = self.scheduler.process

        def tracked(item):
            try:
                process(item)
            finally:
                finished.set()

        self.scheduler.process = tracked
        self.scheduler.spawn_workers(1)
        item = job()
        self.scheduler.enqueue(item)
        self.assertTrue(finished.wait(5), 'worker did not process the job')
        self.assertEqual(item['status'], 'готово')
        self.run_job.assert_called_once_with(item)
