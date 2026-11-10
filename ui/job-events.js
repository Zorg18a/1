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

export function setupJobEvents() {
  const note = document.createElement('p');
  note.className = 'mu';
  note.textContent = 'Очередь и история заданий хранятся в памяти и исчезают при перезапуске MediaHub. Готовые и частичные файлы могут остаться на диске; автоматическое восстановление заданий пока недоступно.';
  document.querySelector('#jobs').before(note);
  const track = createJobTracker();
  window.addEventListener('mediahub:jobs', event => {
    if (!Array.isArray(event.detail)) return;
    for (const message of track(event.detail)) {
      window.dispatchEvent(new CustomEvent('mediahub:notify', {
        detail: { message, label: 'Загрузки', action: () => { window.location.hash = '#downloads'; } },
      }));
    }
  });
}
