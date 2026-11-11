const active = status => /^(качается|в очереди|запл)/.test(status || '');

export function createJobTracker() {
  let previous = null;
  return jobs => {
    const next = new Map();
    const events = [];
    for (const job of jobs) {
      next.set(job.id, job.status);
      if (previous && !active(job.status) && (!previous.has(job.id) || active(previous.get(job.id)))) {
        events.push(`${job.title || job.url || 'Загрузка'}: ${job.status}`);
      }
    }
    previous = next;
    return events;
  };
}

export function summarizeJobs(jobs) {
  if (!Array.isArray(jobs) || jobs.some(job => !job || typeof job.status !== 'string')) return null;
  const counts = { running: 0, queued: 0, scheduled: 0, partial: 0, error: 0, ready: 0, cancelled: 0, skipped: 0, other: 0 };
  for (const { status } of jobs) {
    const key = /^качается/.test(status) ? 'running' : /^в очереди/.test(status) ? 'queued' :
      /^запл/.test(status) ? 'scheduled' : /^(сохранено )?частично/.test(status) ? 'partial' :
      /^ошибка/.test(status) ? 'error' : /^(готово|сохранено)/.test(status) ? 'ready' :
      /^отменено/.test(status) ? 'cancelled' : /^пропущено/.test(status) ? 'skipped' : 'other';
    counts[key]++;
  }
  const text = `Последний ответ: выполняется — ${counts.running}, в очереди — ${counts.queued}, запланировано — ${counts.scheduled}; ` +
    `готово/сохранено — ${counts.ready}, частично — ${counts.partial}, с ошибкой — ${counts.error}, ` +
    `отменено — ${counts.cancelled}, пропущено — ${counts.skipped}, другое — ${counts.other}.`;
  return text + (counts.partial || counts.error ? ' Причины, если известны, указаны у заданий. Перед ручным повтором проверьте очередь, библиотеку и оставшиеся файлы, чтобы не создать дубликаты.' : '');
}

export function createQueueSummary(now = () => performance.now()) {
  let lastTime = null, text = '', started = now();
  return {
    record(jobs) {
      const next = summarizeJobs(jobs);
      if (next === null) return false;
      text = next; lastTime = now(); return true;
    },
    message() {
      const stale = now() - (lastTime ?? started) >= 10000;
      if (!stale) return text || 'Получаем состояние очереди…';
      return (text ? `${text} ` : '') + 'За последние 10 секунд обновление не получено; состояние неизвестно или могло устареть. Проверьте MediaHub и соединение; фоновые вкладки могут обновляться реже.';
    },
  };
}

export function setupJobEvents() {
  const note = document.createElement('p');
  note.className = 'mu';
  note.textContent = 'Очередь и история заданий хранятся в памяти и исчезают при перезапуске MediaHub. Готовые и частичные файлы могут остаться на диске; автоматическое восстановление заданий пока недоступно.';
  const jobs = document.querySelector('#jobs'); jobs.before(note);
  const summary = document.createElement('p'); summary.className = 'mu queue-summary';
  summary.setAttribute('role', 'status'); summary.setAttribute('aria-atomic', 'true'); jobs.before(summary);
  const state = createQueueSummary(), track = createJobTracker();
  const render = () => { const message = state.message(); if (summary.textContent !== message) summary.textContent = message; };
  render(); window.setInterval(render, 1000); document.addEventListener('visibilitychange', render);
  window.addEventListener('mediahub:jobs', event => {
    if (!state.record(event.detail)) return;
    render();
    for (const message of track(event.detail)) {
      window.dispatchEvent(new CustomEvent('mediahub:notify', {
        detail: { message, label: 'Загрузки', action: () => { window.location.hash = '#downloads'; } },
      }));
    }
  });
}
