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
