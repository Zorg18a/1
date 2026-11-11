// Counts reflect the displayed library results, not the total database size.
export function setupLibrarySearch({ doc, win }) {
  const query = doc.getElementById('q');
  query.setAttribute('aria-label', 'Поиск в библиотеке по названию, автору и теме');
  const row = doc.createElement('div'); row.className = 'row';
  const reset = doc.createElement('button'); reset.type = 'button'; reset.className = 'btn';
  reset.textContent = 'Сбросить поиск и тип';
  const status = doc.createElement('p'); status.className = 'mu';
  status.setAttribute('aria-live', 'polite'); status.setAttribute('aria-atomic', 'true');
  row.append(reset, status);
  doc.querySelector('#v-library .tools').append(row);
  let phase = 'pending';
  win.MediaHubLibraryPending = () => { phase = 'pending'; status.textContent = 'Обновляем результаты библиотеки…'; };
  win.MediaHubLibraryLoaded = () => { phase = 'ready'; };
  win.MediaHubLibraryError = () => {
    phase = 'error';
    status.textContent = 'Не удалось обновить библиотеку. На экране могут оставаться прежние результаты. Повторите поиск или сброс.';
  };
  win.MediaHubLibraryDrawn = (count, loadedQuery) => {
    if (phase !== 'ready' || loadedQuery !== query.value || !Number.isSafeInteger(count) || count < 0) return;
    status.textContent = `Показано материалов: ${count}`;
  };
  reset.addEventListener('click', () => {
    query.value = '';
    win.MediaHubLibraryPending();
    win.setK('');
    win.searchNow();
    query.focus();
  });
  win.MediaHubLibraryPending();
  win.searchNow();
}
