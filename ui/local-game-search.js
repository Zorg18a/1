// Explicit, bounded search; candidates are suggestions, never automatic merges.
export function setupLocalGameSearch({ win = window, doc = document, fetcher = fetch } = {}) {
  win.addEventListener('mediahub:game-panel', event => {
    const game = event.detail, panel = doc.querySelector('#gpanel .gb');
    if (!panel || !game?.g || panel.querySelector('.local-game-search')) return;
    const section = doc.createElement('section'); section.className = 'local-game-search';
    const heading = doc.createElement('h4'); heading.textContent = 'Проверить игру на диске';
    const help = doc.createElement('p'); help.className = 'mu';
    help.textContent = 'Поиск по имени в настроенной папке игр и её подпапках до 4 уровней. Совпадения приблизительные: проверьте путь. Связи показаны по снимку записанных путей и могут устареть или не учесть разные имена одного пути. Связать можно папку с карточкой без указанного пути; архивы только показываются. Проверка не запускает игру и не доказывает, что она работает.';
    const button = doc.createElement('button'); button.type = 'button'; button.className = 'btn'; button.textContent = 'Найти игру на диске';
    const status = doc.createElement('p'); status.className = 'mu'; status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');
    const results = doc.createElement('div');
    section.append(heading, help, button, status, results);
    panel.insertBefore(section, panel.querySelector(':scope > h4'));
    let busy = false;
    async function request(body) {
      const response = await fetcher('/api/game/incoming', { method: 'POST',
        headers: { 'X-MH': '1', 'Content-Type': 'application/json' }, body: JSON.stringify({ id: game.id, ...body }) });
      let data;
      try { data = await response.json(); } catch { throw Error('Некорректный ответ сервера'); }
      if (!response.ok) throw Error(typeof data?.error === 'string' ? data.error : 'Не удалось выполнить запрос');
      return data;
    }
    button.addEventListener('click', async () => {
      if (busy) return;
      busy = true; button.disabled = true; results.replaceChildren(); status.textContent = 'Ищу в папке игр…';
      try {
        const data = await request({ mode: 'local_search' });
        if (!data || typeof data.root !== 'string' || !Array.isArray(data.candidates) ||
            data.candidates.length > 100 || typeof data.incomplete !== 'boolean' ||
            !Number.isSafeInteger(data.scanned) || data.scanned < 0) throw Error('Некорректный ответ сервера');
        const candidates = data.candidates;
        status.textContent = `Корень: ${data.root}. Проверено записей: ${data.scanned}. Найдено: ${candidates.length}.` +
          (data.incomplete ? ' Поиск неполный: проверьте структуру папок и пропущенные элементы.' : '') +
          ' Это только возможные совпадения; отсутствие результата не доказывает отсутствия игры.' +
          (candidates.some(c => c?.kind === 'folder' && c.token === null) ? ' Для части папок сейчас нельзя создать подтверждение; повторите поиск позже.' : '');
        const list = doc.createElement('ul');
        for (const candidate of candidates) {
          const association = candidate?.association;
          if (!candidate || typeof candidate.path !== 'string' || typeof candidate.reason !== 'string' ||
              !['folder', 'archive'].includes(candidate.kind) ||
              !['none', 'this', 'other', 'multiple', 'unknown'].includes(association?.state) ||
              !Array.isArray(association.cards) || association.cards.length > 5 ||
              !Number.isSafeInteger(association.extra) || association.extra < 0 ||
              association.cards.some(c => !Number.isSafeInteger(c?.id) || c.id < 1 || typeof c.title !== 'string'))
            throw Error('Некорректный список совпадений');
          const item = doc.createElement('li');
          const description = doc.createElement('span');
          description.textContent = `${candidate.path} — ${candidate.kind === 'folder' ? 'папка' : 'архив'}, ${candidate.reason}. `;
          item.append(description);
          const associationText = doc.createElement('p'); associationText.className = 'mu';
          associationText.textContent = ({ none: 'По снимку путь не связан с карточками игр.', this: 'Путь связан с этой карточкой.',
            other: 'Путь уже связан с другой карточкой.', multiple: 'Путь связан с несколькими карточками; проверьте вручную.',
            unknown: 'Не удалось проверить связи карточек; повторите поиск позже.' })[association.state];
          item.append(associationText);
          for (const card of association.cards) {
            const owner = doc.createElement('span'); owner.textContent = `Карточка: ${card.title || 'Без названия'} (ID ${card.id}). `;
            item.append(owner);
            if (card.id !== game.id && typeof win.openPanel === 'function') {
              const open = doc.createElement('button'); open.type = 'button'; open.className = 'btn';
              open.textContent = 'Открыть карточку'; open.setAttribute('aria-label', `Открыть карточку ${card.title || 'Без названия'}, ID ${card.id}`);
              open.addEventListener('click', () => win.openPanel(card.id)); item.append(open);
            }
          }
          if (association.extra) {
            const more = doc.createElement('p'); more.textContent = `Других связанных карточек: ${association.extra}.`;
            item.append(more);
          }
          if (candidate.kind === 'folder' && association.state === 'none' && typeof candidate.token === 'string') {
            const choose = doc.createElement('button'); choose.type = 'button'; choose.className = 'btn';
            choose.textContent = 'Связать с этой карточкой';
            choose.setAttribute('aria-label', `Связать с карточкой: ${candidate.path}`);
            choose.addEventListener('click', async () => {
              if (busy || !win.confirm(`Связать карточку «${game.title}» с папкой?\n\n${candidate.path}\n\nПроверьте, что это нужная игра. Файлы не перемещаются и не удаляются.`)) return;
              busy = true; button.disabled = true; choose.disabled = true; status.textContent = 'Сохраняю связь…';
              try {
                const saved = await request({ mode: 'local_link', token: candidate.token });
                if (saved?.ok !== 1 || saved.path !== candidate.path) throw Error('Некорректный ответ сервера');
                results.replaceChildren(); status.textContent = 'Связь сохранена. Обновляю карточку…';
                if (typeof win.loadGames === 'function') await win.loadGames();
                else status.textContent = 'Связь сохранена. Обновите список игр.';
              } catch (error) { results.replaceChildren(); status.textContent = `${error.message || 'Ошибка связи'}. Выполните поиск заново и проверьте карточку.`; }
              finally { busy = false; button.disabled = false; choose.disabled = false; }
            });
            item.append(choose);
          }
          list.append(item);
        }
        results.append(list);
      } catch (error) { results.replaceChildren(); status.textContent = error.message || 'Поиск не выполнен'; }
      finally { busy = false; button.disabled = false; }
    });
  });
}
