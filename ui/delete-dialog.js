export function deletionDescription(item) {
  const title = String(item.title || 'Без названия');
  const keep = `«${title}»\n\n«Убрать из библиотеки» удалит запись; файлы останутся на диске.`;
  if (item.kind === 'game') return keep + ' Теги и заметки карточки будут удалены; при сканировании игра может появиться снова.';
  if (item.kind === 'link') return `«${title}»\n\nБудет удалена только запись ссылки, исходная страница не изменится.`;
  if (!item.path) return keep + ' Путь к файлам не указан.';
  if (item.root) return keep + `\n\n«Удалить с диска» также без Корзины удалит папку целиком со всем содержимым:\n${item.root}\nПроверьте путь перед удалением.`;
  return keep + `\n\n«Удалить с диска» без Корзины удалит файл и соседние файлы с тем же базовым именем или дополнительным расширением:\n${item.path}\nПроверьте путь и соседние файлы перед удалением.`;
}

export function setupDeleteDialog() {
  const dialog = document.getElementById('delDlg'), message = document.getElementById('delT');
  const error = document.getElementById('delError');
  const cancel = document.getElementById('delC'), library = document.getElementById('delL'), files = document.getElementById('delF');
  let selected = null, busy = false;
  const controls = [cancel, library, files];
  function open(item) {
    if (!item || busy) return;
    selected = { id: item.id, title: item.title || '', kind: item.kind || '', path: item.path || '', root: item.root || '' };
    message.textContent = deletionDescription(selected);
    error.hidden = true; error.textContent = '';
    files.classList.toggle('hide', selected.kind === 'game' || selected.kind === 'link' || !selected.path);
    dialog.showModal();
  }
  dialog.addEventListener('cancel', event => { if (busy) event.preventDefault(); });
  cancel.addEventListener('click', () => { if (!busy) dialog.close(); });
  async function remove(withFiles) {
    if (!selected || busy) return;
    busy = true; controls.forEach(button => { button.disabled = true; });
    error.hidden = true;
    const item = selected;
    let failure = '';
    try {
      const response = await fetch('/api/delete', { method: 'POST', headers: { 'X-MH': '1', 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: item.id, files: withFiles, expected: { title: item.title, kind: item.kind, path: item.path, root: item.root } }) });
      const result = await response.json();
      if (!response.ok || !result.ok) failure = result.error || 'Не удалось подтвердить удаление. Проверьте библиотеку и файлы.';
    } catch {
      failure = 'Нет ответа сервера; результат неизвестен. Проверьте библиотеку и файлы до повтора.';
    }
    if (failure) {
      error.textContent = failure; error.hidden = false;
      busy = false; controls.forEach(button => { button.disabled = false; });
      return;
    }
    busy = false; controls.forEach(button => { button.disabled = false; });
    dialog.close(); selected = null;
    const inGames = !document.getElementById('v-games').classList.contains('hide');
    if (inGames) { window.closePanel(); window.loadGames().catch(() => {}); }
    else window.lib().catch(() => {});
    document.querySelector(`nav a[href="#${inGames ? 'games' : 'library'}"]`).focus();
    window.toast(withFiles ? 'Запись и найденные файлы удалены' : 'Убрано из библиотеки');
  }
  library.addEventListener('click', () => remove(false));
  files.addEventListener('click', () => remove(true));
  window.MediaHubDelete = { open };
}
