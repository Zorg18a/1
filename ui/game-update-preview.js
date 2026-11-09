function formatBytes(bytes) {
  const n = Number(bytes) || 0;
  if (n < 1024) return `${n} Б`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(2)} КиБ`;
  return n >= 1024 ** 3 ? `${(n / 1024 ** 3).toFixed(2)} ГиБ` : `${(n / 1024 ** 2).toFixed(2)} МиБ`;
}

export async function inspectCandidate(gameId, candidate, button, status) {
  if (button.disabled) return;
  button.disabled = true; status.textContent = 'Проверяю метаданные ZIP…';
  try {
    const response = await fetch('/api/game/zip-inspect', { method: 'POST',
      headers: { 'X-MH': '1', 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: gameId, name: candidate.name, identity: candidate.identity }) });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Не удалось проверить ZIP');
    const summary = result.inspection;
    status.textContent = `Метаданные ZIP прошли предварительную проверку: файлов ${summary.files}, всего ${formatBytes(summary.uncompressed_bytes)}. Содержимое и CRC не проверены; безопасность и завершённость загрузки не подтверждены.`;
  } catch (error) { status.textContent = error.message || 'Не удалось проверить ZIP'; }
  finally { button.disabled = false; }
}

export function setupUpdatePreview() {
  window.addEventListener('mediahub:game-panel', event => {
    const game = event.detail;
    const panel = document.querySelector('#gpanel .gb');
    if (!panel || !game?.g?.downloaded || panel.querySelector('.update-preview')) return;
    const section = document.createElement('section');
    section.className = 'update-preview';
    section.innerHTML = `<h4>Поиск скачанного обновления</h4>
      <p class="mu">Здесь создаётся папка Incoming_Downloads. Скачайте архив вручную с сайта в эту папку; пока карточка открыта, поиск повторяется каждые 15 секунд. Ничего не устанавливается.</p>
      <button type="button" class="btn">Обновить поиск</button>
      <p role="status" aria-live="polite" class="mu"></p><div class="update-results"></div>`;
    const button = section.querySelector('button');
    const status = section.querySelector('[role="status"]');
    const results = section.querySelector('.update-results');
    let lastResult = '', attempted = false;
    const refresh = async (manual = false) => {
      if (button.disabled) return;
      button.disabled = true;
      if (manual || !attempted) status.textContent = 'Ищу архивы…';
      attempted = true;
      try {
        const response = await fetch('/api/game/incoming', { method: 'POST',
          headers: { 'X-MH': '1', 'Content-Type': 'application/json' }, body: JSON.stringify({ id: game.id }) });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Не удалось найти архивы');
        const current = JSON.stringify(data);
        if (!manual && current === lastResult) return;
        const active = document.activeElement;
        const focusedName = active && results.contains(active) ? active.getAttribute('data-zip-name') : null;
        lastResult = current; results.replaceChildren();
        const info = document.createElement('p');
        info.className = 'mu';
        info.textContent = `Папка для скачивания: ${data.folder}. Установлено: ${data.installed_version || 'версия неизвестна'}; на сайте: ${data.latest_version || 'неизвестно'}.`;
        results.append(info);
        if (data.candidates.length) {
          const list = document.createElement('ul');
          for (const candidate of data.candidates) {
            const item = document.createElement('li');
            item.textContent = `${candidate.name} — ${formatBytes(candidate.size)}, версия в имени: ${candidate.version || 'не определена'}`;
            if (candidate.name.toLowerCase().endsWith('.zip') && candidate.identity) {
              const check = document.createElement('button'), report = document.createElement('p');
              check.type = 'button'; check.className = 'btn'; check.textContent = 'Проверить метаданные ZIP';
              check.setAttribute('aria-label', `Проверить метаданные ZIP: ${candidate.name}`);
              check.setAttribute('data-zip-name', candidate.name);
              report.setAttribute('role', 'status'); report.className = 'mu';
              check.addEventListener('click', () => inspectCandidate(game.id, candidate, check, report));
              item.append(check, report);
            }
            list.append(item);
          }
          results.append(list);
        }
        const warning = document.createElement('p');
        warning.className = 'mu';
        warning.textContent = 'Совпадение по имени не подтверждает игру или версию. Содержимое архивов и завершение скачивания не проверены; архивы не распакованы и не изменены.';
        results.append(warning);
        status.textContent = `${data.candidates.length ? `Возможных архивов: ${data.candidates.length}.` : 'Подходящих имён не найдено.'}${data.truncated ? ' Список ограничен, показаны не все файлы.' : ''}`;
        if (focusedName !== null) ([...results.querySelectorAll('[data-zip-name]')].find(el => el.getAttribute('data-zip-name') === focusedName) || button).focus();
      } catch (error) {
        lastResult = ''; results.replaceChildren();
        const message = error.message || 'Не удалось найти архивы';
        if (status.textContent !== message) status.textContent = message;
      }
      finally { button.disabled = false; }
    };
    button.addEventListener('click', () => refresh(true));
    panel.insertBefore(section, panel.querySelector('h4'));
    refresh();
    const timer = window.setInterval(() => {
      if (!section.isConnected || document.querySelector('#gpanel')?.getAttribute('aria-hidden') === 'true' ||
          document.querySelector('#v-games')?.classList.contains('hide')) {
        window.clearInterval(timer);
        return;
      }
      if (!document.hidden) refresh();
    }, 15000);
  });
}
