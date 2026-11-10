// A failure or malformed response cannot prove that the server did not process rows.
export function makePlan(rows, state, onlyLinks) {
  return rows.filter(row => row.status === 'pending').map(row => {
    const choice = state(row);
    let action = choice.on ? choice.action : 'skip';
    if (onlyLinks && action !== 'skip' && action !== 'known') action = 'link';
    return { id: row.id, action, kind: choice.kind };
  });
}

export function createInboxSubmit(fetcher = fetch) {
  const busy = new Set();
  return async function submit(batch, close, rows) {
    if (busy.has(batch)) return { status: 'busy' };
    busy.add(batch);
    try {
      const response = await fetcher('/api/inbox/confirm', {
        method: 'POST', headers: { 'X-MH': '1' },
        body: JSON.stringify({ batch, close, rows }),
      });
      if (!response.ok) throw new Error('HTTP error');
      const result = await response.json();
      if (!result || result.error || !Number.isSafeInteger(result.download) || result.download < 0 ||
          !Number.isSafeInteger(result.links) || result.links < 0) throw new Error('Invalid response');
      const message = `Заданий добавлено: ${result.download}. Ссылок сохранено: ${result.links}. ` +
        (close ? 'Для обработанных вкладок разрешено закрытие; браузер может их не закрыть.' : 'Закрытие вкладок не запрошено.');
      return { status: 'success', message };
    } catch {
      return { status: 'unknown', message: 'Не удалось подтвердить результат. Некоторые строки могли уже обработаться. Проверьте «Входящие», загрузки и библиотеку перед повторной отправкой.' };
    } finally {
      busy.delete(batch);
    }
  };
}

export function createInboxHandler({ getBatch, getClose, state, sending, redraw, status, refresh, submit }) {
  return async (batch, onlyLinks) => {
    const current = getBatch(batch);
    if (!current || sending.size) return;
    const close = !!getClose(batch, current);
    const rows = makePlan(current.rows, state, onlyLinks);
    sending.add(batch);
    redraw();
    status('Отправка плана…');
    try {
      const result = await submit(batch, close, rows);
      status(result.message + (onlyLinks && result.status === 'success'
        ? ' Ранее включённое отслеживание не отключается.' : ''));
      try { await refresh(); } catch { /* The result message remains visible. */ }
    } finally {
      sending.delete(batch);
      redraw();
    }
  };
}

if (typeof window !== 'undefined') {
  window.createInboxHandler = createInboxHandler;
  window.submitInboxPlan = createInboxSubmit();
}
