// Serializes writes from this page and keeps only the latest unsent position.
export function createProgressSaver({ send, status, onDirty = () => {}, onPending = () => {} }) {
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
      onPending(pending.position);
      blocked = error?.code === 'identity-conflict' ? 'conflict' : 'unknown';
      status(blocked);
    } finally {
      active = false;
      if (pending && !blocked) void pump();
    }
  }

  return {
    markDirty,
    submit(position) { markDirty(); pending = { position, version: revision }; onPending(position); if (!blocked) void pump(); },
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
  if (!result || result.error || result.ok !== 1 ||
      ('snapshot' in position && (typeof result.snapshot !== 'string' || !/^[0-9a-f]{64}$/.test(result.snapshot)))) {
    throw new Error('Invalid response');
  }
  return result.snapshot;
}

function describePosition(position, chapters) {
  if (!position || !((typeof position.cid === 'string' && position.cid.length > 0 && position.cid.length <= 1024) ||
      (Number.isSafeInteger(position.cid) && position.cid >= 0)) || !Number.isSafeInteger(position.page) ||
      position.page < 0 || position.page >= Number.MAX_SAFE_INTEGER) return null;
  const id = String(position.cid);
  const chapter = Array.isArray(chapters) ? chapters.find(c => String(c?.id) === id) : null;
  const label = typeof chapter?.label === 'string' ? chapter.label.slice(0, 120) : '';
  return `${label ? label + ' (' : 'Глава ('}ID ${id}), страница ${position.page + 1}`;
}

// A comparison is read-only: it never adopts a fresh snapshot or unblocks writes.
export function setupProgressConflict({ doc, itemId, getSlug, getChapters, fetcher = fetch }) {
  const panel = doc.getElementById('reader-conflict');
  const pendingText = doc.getElementById('reader-conflict-pending');
  const savedText = doc.getElementById('reader-conflict-saved');
  const button = doc.getElementById('reader-conflict-check');
  let pending = null, busy = false;
  function renderPending() {
    const description = describePosition(pending, getChapters());
    pendingText.textContent = description ? `Позиция этой вкладки (сохранение не подтверждено): ${description}.` :
      'Не удалось определить позицию этой вкладки.';
  }
  button.addEventListener('click', async () => {
    if (busy) return;
    busy = true; button.disabled = true; savedText.textContent = 'Проверка сохранённой позиции…';
    try {
      const response = await fetcher('/api/manga/' + encodeURIComponent(itemId));
      if (!response.ok) throw new Error('request failed');
      const data = await response.json();
      if (!data || data.error || data.progress_save_allowed !== true || data.progress_slug !== getSlug()) {
        savedText.textContent = 'Не удалось подтвердить идентичность манги. Проверьте запись и манифест; позицию на сервере нельзя надёжно сопоставить.';
      } else if (data.progress === null) {
        savedText.textContent = 'На момент проверки сохранённой позиции для этой манги нет.';
      } else {
        const description = describePosition(data.progress, data.chapters);
        savedText.textContent = description ? `На момент проверки сохранено: ${description}.` :
          'Сохранённая позиция имеет неизвестный формат. Проверьте данные библиотеки.';
      }
    } catch {
      savedText.textContent = 'Не удалось проверить сохранённую позицию. Проверьте подключение и повторите проверку.';
    } finally {
      busy = false; button.disabled = false;
    }
  });
  return {
    update(position) { pending = position; renderPending(); },
    show() { panel.hidden = false; renderPending(); },
  };
}
