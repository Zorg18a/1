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
    submit(position) {
      markDirty();
      if (blocked === 'conflict' && pending && ['id', 'cid', 'page', 'slug'].every(k => pending.position[k] === position[k])) {
        pending.version = revision; return;
      }
      pending = { position, version: revision }; onPending(position); if (!blocked) void pump();
    },
    retry() { if (blocked === 'unknown' && !active) { blocked = false; void pump(); } },
    resolveConflict(position, prepare) {
      if (blocked !== 'conflict' || active || !pending || pending.position !== position || pending.version !== revision) return false;
      prepare(); blocked = false; void pump(); return true;
    },
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
  const safe = value => value.replace(/[\x00-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]/g, '�');
  const label = typeof chapter?.label === 'string' ? safe(chapter.label.slice(0, 120)) : '';
  return `${label ? label + ' (' : 'Глава ('}ID ${safe(id)}), страница ${position.page + 1}`;
}

// Checking never writes; applying requires confirmation and the exact checked snapshot.
export function setupProgressConflict({ doc, itemId, getSlug, getIdentity, getChapters, fetcher = fetch,
  confirm, onResolve, onStart = () => {} }) {
  const panel = doc.getElementById('reader-conflict');
  const pendingText = doc.getElementById('reader-conflict-pending');
  const savedText = doc.getElementById('reader-conflict-saved');
  const button = doc.getElementById('reader-conflict-check');
  const apply = doc.getElementById('reader-conflict-apply');
  let pending = null, busy = false, choice = null, change = 0;
  function invalidate() {
    change++;
    if (choice) savedText.textContent = 'Позиция вкладки изменилась. Проверьте сохранённую позицию ещё раз.';
    const focused = doc.activeElement === apply;
    choice = null; apply.disabled = true;
    if (focused) button.focus({ preventScroll: true });
  }
  function renderPending() {
    const description = describePosition(pending, getChapters());
    pendingText.textContent = description ? `Позиция этой вкладки (сохранение не подтверждено): ${description}.` :
      'Не удалось определить позицию этой вкладки.';
  }
  button.addEventListener('click', async () => {
    if (busy) return;
    choice = null; apply.disabled = true;
    const checkedChange = change, checkedPending = pending;
    busy = true; button.disabled = true; savedText.textContent = 'Проверка сохранённой позиции…';
    try {
      const response = await fetcher('/api/manga/' + encodeURIComponent(itemId));
      if (!response.ok) throw new Error('request failed');
      const data = await response.json();
      if (!data || data.error || data.progress_save_allowed !== true || data.progress_slug !== getSlug() ||
          typeof data.progress_identity !== 'string' || !/^[0-9a-f]{64}$/.test(data.progress_identity) ||
          data.progress_identity !== getIdentity()) {
        savedText.textContent = 'Не удалось подтвердить идентичность манги. Проверьте запись и манифест; позицию на сервере нельзя надёжно сопоставить.';
        return;
      }
      const saved = data.progress === null ? 'Сохранённой позиции нет' : describePosition(data.progress, data.chapters);
      if (!saved) {
        savedText.textContent = 'Сохранённая позиция имеет неизвестный формат. Проверьте данные библиотеки.';
        return;
      }
      savedText.textContent = `На момент проверки: ${saved}.`;
      if (checkedChange !== change || checkedPending !== pending) {
        savedText.textContent += ' Позиция вкладки изменилась; проверьте ещё раз.';
      } else if (typeof data.progress_snapshot !== 'string' || !/^[0-9a-f]{64}$/.test(data.progress_snapshot) ||
                 !describePosition(pending, getChapters())) {
        savedText.textContent += ' Нельзя подтвердить снимок или позицию вкладки; сохранение недоступно.';
      } else {
        choice = { position: pending, snapshot: data.progress_snapshot, saved };
        apply.disabled = false;
      }
    } catch {
      savedText.textContent = 'Не удалось проверить сохранённую позицию. Проверьте подключение и повторите проверку.';
    } finally {
      busy = false; button.disabled = false;
    }
  });
  apply.addEventListener('click', () => {
    if (!choice || busy) return;
    const selected = choice;
    const local = describePosition(selected.position, getChapters());
    if (!local || selected.position !== pending) { invalidate(); return; }
    if (!confirm(`Заменить сохранённую позицию?\n\nБыло на момент проверки: ${selected.saved}.\n` +
                 `Сохранить из этой вкладки: ${local}.\n\nПосле подтверждения автосохранение продолжится.`)) return;
    if (choice !== selected) return;
    choice = null; apply.disabled = true;
    if (!onResolve(selected.snapshot, selected.position)) {
      savedText.textContent = 'Позиция вкладки изменилась. Проверьте сохранённую позицию ещё раз.';
      button.focus({ preventScroll: true });
      return;
    }
    panel.hidden = true;
    onStart();
  });
  return {
    update(position) { if (pending !== position) invalidate(); pending = position; renderPending(); },
    invalidate,
    show() { invalidate(); savedText.textContent = 'Проверьте сохранённую позицию перед выбором.'; panel.hidden = false; renderPending(); },
  };
}
