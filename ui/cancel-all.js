const active = job => /^(качается|в очереди|запл)/.test(job.status || '');

// Only cancel the snapshot the user confirmed, never newly added jobs.
export async function cancelSnapshot({ getJobs, cancel, confirm }) {
  const jobs = await getJobs();
  if (!Array.isArray(jobs)) throw new Error('Не удалось получить список заданий');
  const ids = [...new Set(jobs.filter(active).map(job => job.id).filter(Number.isSafeInteger))];
  if (!ids.length) return { status: 'empty', count: 0, failed: 0 };
  const message = `Запросить отмену заданий: ${ids.length}?\n\n` +
    'Включены текущие, ожидающие и запланированные задания. Новые задания не затрагиваются. ' +
    'Остановка может произойти не сразу. Уже сохранённые и частично загруженные файлы могут остаться на диске. ' +
    'Для ежедневных заданий уже созданные будущие запуски отменяются только если они входят в этот список.';
  if (!confirm(message)) return { status: 'declined', count: ids.length, failed: 0 };
  let failed = 0;
  for (const id of ids) {
    try { await cancel(id); } catch { failed++; }
  }
  return { status: 'requested', count: ids.length, failed };
}

export function setupCancelAll() {
  const button = document.querySelector('#cxl');
  async function request(url, body) {
    const response = await fetch(url, body && { method: 'POST', headers: { 'X-MH': '1' }, body: JSON.stringify(body) });
    if (!response.ok) throw new Error('HTTP ' + response.status);
    const result = await response.json();
    if (result.error) throw new Error(String(result.error));
    return result;
  }
  function notify(message) {
    window.dispatchEvent(new CustomEvent('mediahub:notify', { detail: { message } }));
  }
  button.addEventListener('click', async () => {
    button.disabled = true;
    try {
      const result = await cancelSnapshot({
        getJobs: () => request('/api/jobs'),
        cancel: id => request('/api/cancel', { id }),
        confirm: message => window.confirm(message),
      });
      if (result.status === 'empty') notify('Нет активных или запланированных заданий.');
      if (result.status === 'requested') notify(result.failed
        ? `Запрос отмены отправлен не для всех заданий: ${result.failed} из ${result.count} не подтверждены сервером. Проверьте список.`
        : `Отмена запрошена для заданий: ${result.count}. Проверьте их состояние в списке.`);
    } catch {
      notify('Не удалось получить список заданий. Отмена не отправлена; проверьте подключение.');
    } finally {
      button.disabled = false;
      button.focus();
      if (typeof window.poll === 'function') window.poll();
    }
  });
  button.disabled = false;
}
