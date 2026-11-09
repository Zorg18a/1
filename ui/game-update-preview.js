function formatBytes(bytes) {
  const n = Number(bytes) || 0;
  if (n < 1024) return `${n} Б`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(2)} КиБ`;
  return n >= 1024 ** 3 ? `${(n / 1024 ** 3).toFixed(2)} ГиБ` : `${(n / 1024 ** 2).toFixed(2)} МиБ`;
}

export async function inspectCandidate(gameId, candidate, button, status, verifyData = false) {
  if (button.disabled) return;
  button.disabled = true; status.textContent = verifyData ? 'Проверяю данные и CRC ZIP…' : 'Проверяю метаданные ZIP…';
  try {
    const response = await fetch('/api/game/zip-inspect', { method: 'POST',
      headers: { 'X-MH': '1', 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: gameId, name: candidate.name, identity: candidate.identity, ...(verifyData ? { verify_data: true } : {}) }) });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Не удалось проверить ZIP');
    const summary = result.inspection;
    status.textContent = verifyData
      ? `Данные и CRC проверены: файлов ${summary.verified_files}, всего ${formatBytes(summary.verified_bytes)}. Это не подтверждает безопасность, подлинность или завершённость загрузки; архив не установлен.`
      : `Метаданные ZIP прошли предварительную проверку: файлов ${summary.files}, всего ${formatBytes(summary.uncompressed_bytes)}. Содержимое и CRC не проверены; безопасность и завершённость загрузки не подтверждены.`;
  } catch (error) { status.textContent = error.message || 'Не удалось проверить ZIP'; }
  finally { button.disabled = false; }
}

export async function compareCandidate(gameId, candidate, button, status, results) {
  if (button.disabled) return;
  button.disabled = true; results.replaceChildren(); status.textContent = 'Сопоставляю возможные сохранения с путями ZIP…';
  try {
    const response = await fetch('/api/game/zip-inspect', { method: 'POST',
      headers: { 'X-MH': '1', 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: gameId, name: candidate.name, identity: candidate.identity, compare_saves: true }) });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Не удалось сопоставить пути');
    const preview = data.inspection.save_comparison;
    const labels = { file_same_path: 'совпадает путь файла в ZIP', directory_shared: 'папка или её элементы есть в ZIP; содержимое не сравнивалось',
      type_conflict: 'конфликт типов файл/папка', ancestor_file: 'на пути в ZIP находится файл', not_found: 'совпадающий путь в ZIP не найден',
      unsupported_name: 'имя нельзя сопоставить с ZIP' };
    status.textContent = `Папка игры: ${preview.game_folder}. Расположений: ${preview.candidates.length}.${preview.incomplete ? ' Поиск неполный.' : ''} Пути сравниваются от корней папки игры и ZIP, без определения обёртки; AppData, облако и содержимое папок не проверены. Отсутствие совпадений не исключает конфликты. Локальные заголовки, данные и CRC не проверены; это не план установки или резервная копия.`;
    const list = document.createElement('ul');
    for (const entry of preview.candidates) {
      const item = document.createElement('li');
      item.textContent = `${entry.path}: ${labels[entry.relation] || 'неизвестный результат'}`;
      list.append(item);
    }
    results.append(list);
  } catch (error) { status.textContent = error.message || 'Не удалось сопоставить пути'; }
  finally { button.disabled = false; }
}

export function setupSavePreview(gameId, section) {
  const button = section.querySelector('.save-preview-button');
  const status = section.querySelector('.save-preview-status');
  const results = section.querySelector('.save-preview-results');
  button.addEventListener('click', async () => {
    if (button.disabled) return;
    button.disabled = true; results.replaceChildren(); status.textContent = 'Ищу возможные сохранения…';
    try {
      const response = await fetch('/api/game/incoming', { method: 'POST',
        headers: { 'X-MH': '1', 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: gameId, mode: 'saves' }) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Не удалось найти сохранения');
      const preview = data.save_preview;
      status.textContent = `Папка игры: ${preview.game_folder}. Возможных расположений: ${preview.candidates.length}.${preview.incomplete ? ' Поиск неполный: достигнут лимит или пропущены элементы.' : ''} Это не резервная копия; AppData и облачные сохранения не проверяются.`;
      const list = document.createElement('ul');
      for (const candidate of preview.candidates) {
        const item = document.createElement('li');
        item.textContent = `${candidate.path} (${candidate.kind === 'directory' ? 'папка' : 'файл'})`;
        list.append(item);
      }
      results.append(list);
    } catch (error) { status.textContent = error.message || 'Не удалось найти сохранения'; }
    finally { button.disabled = false; }
  });
}

export function setupUpdatePreview() {
  window.addEventListener('mediahub:game-panel', event => {
    const game = event.detail;
    const panel = document.querySelector('#gpanel .gb');
    if (!panel || !game?.g?.downloaded || panel.querySelector('.update-preview')) return;
    const section = document.createElement('section');
    section.className = 'update-preview';
    section.innerHTML = `<h4>Поиск скачанного обновления</h4>
      <p class="mu">Здесь создаётся папка Incoming_Downloads. Скачайте архив вручную с сайта в эту папку; пока карточка открыта, поиск повторяется каждые 15 секунд. Ничего не устанавливается. Проверка данных ZIP ограничена 128 МиБ сжатых и 256 МиБ распакованных данных.</p>
      <button type="button" class="btn">Обновить поиск</button>
      <p role="status" aria-live="polite" class="mu"></p><div class="update-results"></div>
      <h4>Возможные сохранения</h4>
      <p class="mu">Поиск по именам только внутри папки игры, без чтения содержимого и копирования. Другие расположения могут быть пропущены.</p>
      <button type="button" class="btn save-preview-button">Найти возможные сохранения</button>
      <p role="status" aria-live="polite" class="mu save-preview-status"></p><div class="save-preview-results"></div>`;
    setupSavePreview(game.id, section);
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
        const focusedMode = active?.getAttribute('data-zip-mode');
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
              const check = document.createElement('button'), verify = document.createElement('button'), compare = document.createElement('button');
              const report = document.createElement('p'), comparison = document.createElement('div');
              check.type = 'button'; check.className = 'btn'; check.textContent = 'Проверить метаданные ZIP';
              check.setAttribute('aria-label', `Проверить метаданные ZIP: ${candidate.name}`);
              check.setAttribute('data-zip-name', candidate.name); check.setAttribute('data-zip-mode', 'metadata');
              verify.type = 'button'; verify.className = 'btn'; verify.textContent = 'Проверить данные и CRC ZIP';
              verify.setAttribute('aria-label', `Проверить данные и CRC ZIP: ${candidate.name}`);
              verify.setAttribute('data-zip-name', candidate.name); verify.setAttribute('data-zip-mode', 'data');
              compare.type = 'button'; compare.className = 'btn'; compare.textContent = 'Сопоставить пути сохранений с ZIP';
              compare.setAttribute('aria-label', `Сопоставить пути сохранений с ZIP: ${candidate.name}`);
              compare.setAttribute('data-zip-name', candidate.name); compare.setAttribute('data-zip-mode', 'compare');
              report.setAttribute('role', 'status'); report.className = 'mu';
              const actions = [check, verify, compare];
              const run = async (selected, action) => {
                if (actions.some(el => el.disabled)) return;
                actions.filter(el => el !== selected).forEach(el => { el.disabled = true; });
                comparison.replaceChildren();
                try { await action(); }
                finally { actions.forEach(el => { el.disabled = false; }); }
              };
              check.addEventListener('click', () => run(check, () => inspectCandidate(game.id, candidate, check, report)));
              verify.addEventListener('click', () => run(verify, () => inspectCandidate(game.id, candidate, verify, report, true)));
              compare.addEventListener('click', () => run(compare, () => compareCandidate(game.id, candidate, compare, report, comparison)));
              item.append(check, verify, compare, report, comparison);
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
        if (focusedName !== null) ([...results.querySelectorAll('[data-zip-name]')].find(el => el.getAttribute('data-zip-name') === focusedName && el.getAttribute('data-zip-mode') === focusedMode) || button).focus();
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
