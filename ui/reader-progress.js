// Serializes writes from this page and keeps only the latest unsent position.
export function createProgressSaver({ send, status, onDirty = () => {} }) {
  let pending = null, active = false, blocked = false, dirty = false, revision = 0;

  function markDirty() {
    revision++;
    if (!dirty) { dirty = true; onDirty(true); }
    if (!blocked) status('dirty');
  }
  function markClean() {
    if (dirty) { dirty = false; onDirty(false); }
  }
  async function pump() {
    if (active || blocked || !pending) return;
    const { position, version } = pending;
    pending = null;
    active = true;
    status('saving');
    try {
      await send(position);
      if (!pending && version === revision) { markClean(); status('saved'); }
    } catch (error) {
      pending = pending || { position, version };
      blocked = error?.code === 'identity-conflict' ? 'conflict' : 'unknown';
      status(blocked);
    } finally {
      active = false;
      if (pending && !blocked) void pump();
    }
  }

  return {
    markDirty,
    submit(position) { markDirty(); pending = { position, version: revision }; if (!blocked) void pump(); },
    retry() { if (blocked === 'unknown' && !active) { blocked = false; void pump(); } },
  };
}

export async function sendProgress(position, fetcher = fetch) {
  const response = await fetcher('/api/progress', {
    method: 'POST', headers: { 'X-MH': '1', 'Content-Type': 'application/json' },
    body: JSON.stringify(position),
  });
  if (response.status === 409) throw Object.assign(new Error('Item changed'), { code: 'identity-conflict' });
  if (!response.ok) throw new Error('HTTP');
  const result = await response.json();
  if (!result || result.error || result.ok !== 1) throw new Error('Invalid response');
}
