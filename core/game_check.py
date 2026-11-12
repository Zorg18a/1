"""Session-only checkpoints for explicit continuation of game checks.

A started attempt is removed from pending before network access. A failure is
reported as unknown and never automatically retried by continuation.
"""
from collections import deque
import threading
import time

_LOCK = threading.Lock()
_MAX_ITEMS = 50000


def _thread(row, ginfo):
    return ginfo(row).get('meta', {}).get('thread') or ''


def run(job, online, sql, ginfo, fetch, parse, apply, delay):
    batch = job.get('_game_batch')
    if batch is None:
        requested = job.get('ids')
        rows = (sql("select * from items where kind='game'") if requested is None else
                [row for rid in requested for row in sql('select * from items where id=?', (rid,))])
        entries = [(r['id'], r['url'], _thread(r, ginfo), r['title']) for r in rows
                   if r['kind'] == 'game' and _thread(r, ginfo)]
        if len(entries) > _MAX_ITEMS:
            raise RuntimeError('Слишком много игр для проверки за один раз')
        batch = {'pending': deque(entries), 'total': len(entries), 'ok': 0, 'unknown': 0,
                 'skipped': 0, 'updated': 0, 'errors': []}
        with _LOCK:
            job['_game_batch'] = batch
    if not online():
        raise RuntimeError('расширение MediaHub не на связи: откройте браузер с установленным расширением')
    while True:
        with _LOCK:
            if job['cancel'] or not batch['pending']:
                break
            rid, url, thread, title = batch['pending'].popleft()
            batch['unknown'] += 1  # If interrupted, never silently retry an uncertain attempt.
            position = batch['total'] - len(batch['pending'])
        job['title'] = f"Проверка игр {position}/{batch['total']}: {title}"
        job['pct'] = int((position - 1) * 100 / max(1, batch['total']))
        try:
            rows = sql('select * from items where id=?', (rid,))
            if not rows or rows[0]['kind'] != 'game' or rows[0]['url'] != url or _thread(rows[0], ginfo) != thread:
                with _LOCK:
                    batch['unknown'] -= 1
                    batch['skipped'] += 1
                continue
            old = ginfo(rows[0]).get('meta', {}).get('version', '')
            meta = parse(fetch(thread, job), thread)
            if meta.get('blocked'):
                raise RuntimeError('проверка Cloudflare: пройдите её в браузере')
            if not meta['name']:
                raise RuntimeError('страница не открылась')
            apply(meta, thread)
            with _LOCK:
                batch['unknown'] -= 1
                batch['ok'] += 1
                batch['updated'] += int(bool(meta.get('version') and meta['version'] != old))
        except Exception as exc:
            with _LOCK:
                batch['last_error'] = f"{title}: {str(exc)[:60]}"
                if len(batch['errors']) < 5:
                    batch['errors'].append({'id': rid, 'title': str(title or '')[:160], 'reason': str(exc)[:120]})
        with _LOCK:
            more = bool(batch['pending'])
        if more and delay and not job['cancel']:
            time.sleep(delay)
    with _LOCK:
        state = 'частично' if batch['unknown'] or batch['skipped'] else 'готово'
        job['final'] = (f"{state}: проверено {batch['ok']}, изменилась версия у {batch['updated']}, "
                        f"неизвестно/ошибка {batch['unknown']}, пропущено {batch['skipped']}" +
                        (f" ({batch['last_error']})" if batch.get('last_error') else ''))


def snapshot(job):
    with _LOCK:
        batch = job.get('_game_batch')
        if not batch:
            return None
        return {'total': batch['total'], 'pending': len(batch['pending']), 'ok': batch['ok'],
                'unknown': batch['unknown'], 'skipped': batch['skipped'], 'errors': list(batch['errors']),
                'resume': bool(batch['pending'] and not job.get('_game_claimed') and
                               job.get('status', '').startswith(('отменено', 'ошибка', 'готово', 'частично')))}


def resume(data, jobs, new_job):
    source_id = data.get('resume')
    if type(source_id) is not int or source_id < 1:
        return {'error': 'Некорректное задание'}, 400
    with _LOCK:
        source = jobs.get(source_id)
        batch = source.get('_game_batch') if source and source.get('kind') == 'gamecheck' else None
        if (not batch or not batch['pending'] or source.get('_game_claimed') or
                not source.get('status', '').startswith(('отменено', 'ошибка', 'готово', 'частично'))):
            return {'error': 'Продолжение недоступно: проверьте очередь и обновите её.'}, 409
        source['_game_claimed'] = True
        next_batch = dict(batch, pending=deque(batch['pending']), errors=list(batch['errors']))
        try:
            job_id = new_job('games:resume', 'gamecheck', _game_batch=next_batch, title='Продолжение проверки игр')
        except Exception:
            source['_game_claimed'] = False
            raise
    return {'job': job_id}, 200
