import { requestPreflight } from './download-preflight.js';

// Optional, read-only snapshot; it never submits the add dialog.
export function setupDialogPreflight({ doc = document, win = window, fetcher = fetch } = {}) {
  const dialog = doc.getElementById('addDlg'), preview = doc.getElementById('pv');
  const folder = doc.getElementById('s_folder');
  if (!dialog || !preview || !folder) return;
  const details = doc.createElement('details'); details.className = 'more';
  const summary = doc.createElement('summary'); summary.textContent = 'Проверка условий загрузки (необязательно)';
  const content = doc.createElement('div');
  const info = doc.createElement('p'); info.className = 'mu';
  info.textContent = 'Проверяется сохранённая папка и инструменты. Данные могут устареть; права записи, сайт, достаточность места и успех загрузки не гарантируются. Проверка не запускает загрузку.';
  const button = doc.createElement('button'); button.type = 'button'; button.className = 'btn';
  button.textContent = 'Проверить условия загрузки';
  const status = doc.createElement('p'); status.setAttribute('role', 'status');
  const list = doc.createElement('ul'); list.style.overflowWrap = 'anywhere';
  content.append(info, button, status, list); details.append(summary, content); preview.before(details);
  let generation = 0, busy = false, controller;
  const clear = () => { ++generation; controller?.abort(); list.replaceChildren(); status.textContent = ''; };
  dialog.addEventListener('close', () => { clear(); details.open = false; });
  const folderChanged = () => {
    clear();
    if (dialog.open) status.textContent = 'Папка изменена. Дождитесь сохранения настройки и повторите проверку.';
  };
  folder.addEventListener('input', folderChanged); folder.addEventListener('change', folderChanged);
  button.addEventListener('click', async () => {
    if (busy) return;
    busy = true; button.disabled = true; const ticket = ++generation;
    status.textContent = 'Проверяем сохранённые настройки…'; list.replaceChildren();
    controller = new AbortController();
    try {
      const { data, lines } = await requestPreflight({ fetcher, win, controller });
      if (ticket !== generation || !dialog.open) return;
      const path = data.folder ? `Сохранённая папка на момент проверки: ${data.folder}` : 'Сохранённая папка не задана или некорректна.';
      for (const line of [path, ...lines]) { const item = doc.createElement('li'); item.textContent = line; list.append(item); }
      status.textContent = 'Проверка завершена. Результат может устареть; он не гарантирует успешную загрузку.';
    } catch (error) {
      if (ticket === generation && dialog.open) status.textContent = `Проверка не выполнена: ${error?.message || 'нет связи с MediaHub'}`;
    } finally { controller = undefined; busy = false; button.disabled = false; }
  });
}
