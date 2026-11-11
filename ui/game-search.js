// The game grid applies its filters locally to the most recently loaded library.
export function setupGameSearch({ doc, win }) {
  const query = doc.getElementById('gq');
  query.setAttribute('aria-label', 'Поиск игр по названию, разработчику, жанру, тегу или движку');
  const row = doc.createElement('div'); row.className = 'gtools';
  const reset = doc.createElement('button'); reset.type = 'button'; reset.className = 'btn';
  reset.textContent = 'Сбросить поиск и фильтры игр';
  const retry = doc.createElement('button'); retry.type = 'button'; retry.className = 'btn';
  retry.textContent = 'Обновить список игр';
  const status = doc.createElement('p'); status.className = 'mu';
  status.setAttribute('aria-live', 'polite'); status.setAttribute('aria-atomic', 'true');
  row.append(reset, retry, status);
  doc.querySelector('#gtab-lib .gtools').after(row);
  let phase = 'pending';
  win.MediaHubGamesPending = () => { phase = 'pending'; status.textContent = 'Обновляем список игр…'; };
  win.MediaHubGamesLoaded = () => { phase = 'ready'; };
  win.MediaHubGamesError = () => {
    phase = 'error'; status.textContent = 'Не удалось обновить игры. На экране могут оставаться прежние результаты. Обновите список игр.';
  };
  win.MediaHubGamesDrawn = (count, total) => {
    if (phase !== 'ready' || !Number.isSafeInteger(count) || !Number.isSafeInteger(total) || count < 0 || total < count) return;
    status.textContent = `Показано игр: ${count} из ${total}`;
  };
  reset.addEventListener('click', () => { win.resetGameFilters(); query.focus(); });
  retry.addEventListener('click', () => { void win.loadGames(); });
  win.MediaHubGamesPending();
  if (!doc.getElementById('v-games').classList.contains('hide') &&
      !doc.getElementById('gtab-lib').classList.contains('hide')) void win.loadGames();
}
