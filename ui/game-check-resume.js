// Continuation is explicit and only covers pending items in the running app session.
export function setupGameCheckResume({ win = window, doc = document, fetcher = fetch } = {}) {
  const jobs = doc.querySelector('#jobs');
  if (!jobs) return;
  const section = doc.createElement('section'); section.className = 'game-check-resume';
  const heading = doc.createElement('h3'); heading.textContent = 'Продолжение проверки игр';
  const help = doc.createElement('p'); help.className = 'mu';
  help.textContent = 'Можно продолжить только ещё не начатые темы. Ошибки и неизвестные результаты автоматически не повторяются. Состояние хранится только до перезапуска приложения или очистки заданий; новый полный запуск проверяет всё заново.';
  const status = doc.createElement('p'); status.className = 'mu'; status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');
  const list = doc.createElement('div'); section.append(heading, help, status, list); jobs.before(section);
  let busy = false, waiting = false, signature = '';
  win.addEventListener('mediahub:jobs', event => {
    if (!Array.isArray(event.detail)) return;
    const next = JSON.stringify(event.detail.map(j => [j?.id, j?.kind, j?.status, j?.game_check]));
    const wasWaiting = waiting; waiting = false;
    if (next === signature && !wasWaiting) return;
    signature = next; list.replaceChildren();
    for (const job of event.detail) {
      const s = job?.game_check;
      if (job.kind !== 'gamecheck' || !s || !Number.isSafeInteger(job.id) ||
          !['total', 'pending', 'ok', 'unknown', 'skipped'].every(k => Number.isSafeInteger(s[k]) && s[k] >= 0) || typeof s.resume !== 'boolean' ||
          !Array.isArray(s.errors) || s.errors.length > 5 || s.errors.some(e => !Number.isSafeInteger(e?.id) || typeof e.title !== 'string' || typeof e.reason !== 'string')) continue;
      const row = doc.createElement('div');
      const text = doc.createElement('p'); text.textContent = `Задание ${job.id}: ${job.status}. Всего ${s.total}, проверено ${s.ok}, осталось ${s.pending}, ошибок или неизвестно ${s.unknown}, пропущено ${s.skipped}.`;
      row.append(text);
      for (const error of s.errors) {
        const detail = doc.createElement('p'); detail.className = 'mu';
        detail.textContent = `Неизвестно или ошибка: ${error.title || 'Без названия'} (ID ${error.id}) — ${error.reason || 'причина не указана'}.`;
        row.append(detail);
      }
      if (s.resume) {
        const button = doc.createElement('button'); button.type = 'button'; button.className = 'btn';
        button.textContent = 'Продолжить оставшиеся'; button.disabled = busy;
        button.setAttribute('aria-label', `Продолжить оставшиеся темы задания ${job.id}`);
        button.addEventListener('click', async () => {
          if (busy || waiting) return;
          busy = true; button.disabled = true; status.textContent = 'Отправляю запрос…';
          const controller = new AbortController(); const timer = win.setTimeout(() => controller.abort(), 15000);
          try {
            const response = await fetcher('/api/game/check', { method: 'POST',
              headers: { 'X-MH': '1', 'Content-Type': 'application/json' },
              body: JSON.stringify({ resume: job.id }), signal: controller.signal });
            const data = await response.json();
            if (!response.ok) throw Error(data?.error || 'Не удалось продолжить');
            if (!Number.isSafeInteger(data?.job) || data.job < 1) throw Error('Некорректный ответ сервера');
            status.textContent = `Продолжение добавлено в очередь как задание ${data.job}.`;
          } catch (error) {
            status.textContent = `${error.message || 'Нет ответа'}. Результат запроса может быть неизвестен: проверьте очередь перед повтором.`;
          } finally {
            win.clearTimeout(timer); busy = false; waiting = true;
            if (typeof win.poll === 'function') win.poll();
          }
        });
        row.append(button);
      }
      list.append(row);
    }
  });
}
