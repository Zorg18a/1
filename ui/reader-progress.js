// Serializes writes from this page and keeps only the latest unsent position.
export function createProgressSaver({ send, status }) {
  let pending = null, active = false, blocked = false;

  async function pump() {
    if (active || blocked || !pending) return;
    const position = pending;
    pending = null;
    active = true;
    status('saving');
    try {
      await send(position);
      if (!pending) status('saved');
    } catch {
      pending = pending || position;
      blocked = true;
      status('unknown');
    } finally {
      active = false;
      if (pending && !blocked) void pump();
    }
  }

  return {
    submit(position) { pending = position; if (!blocked) void pump(); },
    retry() { if (blocked && !active) { blocked = false; void pump(); } },
  };
}

export async function sendProgress(position, fetcher = fetch) {
  const response = await fetcher('/api/progress', {
    method: 'POST', headers: { 'X-MH': '1', 'Content-Type': 'application/json' },
    body: JSON.stringify(position),
  });
  if (!response.ok) throw new Error('HTTP');
  const result = await response.json();
  if (!result || result.error || result.ok !== 1) throw new Error('Invalid response');
}
