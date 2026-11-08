"""In-memory job queue and delayed scheduling, independent of download handlers."""
import queue
import threading
import time
from datetime import datetime


class JobQueue:
    def __init__(self, jobs, ids, run_job):
        self.jobs = jobs
        self.ids = ids
        self.run_job = run_job
        self.pending = queue.Queue()
        self.worker_count = 0

    def enqueue(self, job):
        self.jobs[job['id']] = job
        if job['start_at'] > time.time():
            job['status'] = 'запланировано ' + datetime.fromtimestamp(job['start_at']).strftime('%d.%m %H:%M')
            timer = threading.Timer(job['start_at'] - time.time(), self.fire, (job,))
            timer.daemon = True
            timer.start()
        else:
            self.pending.put(job)

    def fire(self, job):
        if job['cancel']:
            return
        job['status'] = 'в очереди'
        self.pending.put(job)
        if job['daily']:
            self.enqueue(dict(job, id=next(self.ids), start_at=job['start_at'] + 86400,
                              cancel=False, pct=0, speed=0))

    def process(self, job):
        if job['cancel']:
            job['status'] = 'отменено'
            return
        job['status'] = 'качается'
        try:
            self.run_job(job)
            job['status'] = 'отменено' if job['cancel'] else job.pop('final', 'готово')
            job['pct'] = 100
        except Exception as exc:
            job['status'] = 'отменено' if job['cancel'] else 'ошибка: ' + str(exc)[:150]
        job['speed'] = 0

    def worker(self):
        while True:
            self.process(self.pending.get())

    def spawn_workers(self, count):
        # Compatibility: reducing the setting does not stop existing workers.
        while self.worker_count < count:
            threading.Thread(target=self.worker, daemon=True).start()
            self.worker_count += 1
