const folderText = {
  directory: 'Сохранённая папка существует.', missing: 'Сохранённая папка не найдена; приложение может попытаться создать её при загрузке.',
  not_directory: 'Сохранённый путь не является папкой.', relative: 'Сохранён путь относительно рабочей папки; место не проверено.',
  network_skipped: 'Сетевой путь не проверялся.', invalid: 'Сохранённый путь некорректен или пуст.',
  unknown: 'Не удалось проверить сохранённую папку.',
};
const toolText = { found: 'файл найден', missing: 'не найден', unknown: 'не удалось проверить' };

export function describePreflight(data) {
  const dir = data?.directory, tools = data?.tools;
  if (!dir || !Object.hasOwn(folderText, dir.state) || !tools ||
      !['app_folder', 'path', 'unknown'].includes(tools.source) ||
      !Object.hasOwn(toolText, tools.ffmpeg) || !Object.hasOwn(toolText, tools.ffprobe) ||
      typeof data.extension_online !== 'boolean' || !(typeof data.folder === 'string' || data.folder === null) ||
      !(dir.free_bytes === null || (typeof dir.free_bytes === 'string' && /^[0-9]{1,24}$/.test(dir.free_bytes)))) {
    throw new Error('Сервер вернул некорректный ответ.');
  }
  const space = dir.state === 'directory' && dir.free_bytes !== null
    ? `Свободно на диске примерно ${BigInt(dir.free_bytes) / 1048576n} МиБ на момент проверки.`
    : 'Свободное место не определено.';
  const source = tools.source === 'app_folder' ? 'в папке ffmpeg приложения' : tools.source === 'path' ? 'в PATH процесса' : 'источник неизвестен';
  return [folderText[dir.state], space,
    `ffmpeg: ${toolText[tools.ffmpeg]}; ffprobe: ${toolText[tools.ffprobe]} (${source}).`,
    data.extension_online ? 'Расширение недавно выходило на связь.' : 'Недавней связи с расширением не обнаружено.'];
}

export function setupDownloadPreflight({ doc = document, win = window, fetcher = fetch } = {}) {
  const parent = doc.querySelector('#v-settings .set'), folder = doc.getElementById('s_folder');
  if (!parent || !folder) return;
  const panel = doc.createElement('section'); panel.className = 'sg';
  const heading = doc.createElement('h2'); heading.textContent = 'Проверка перед загрузкой';
  const info = doc.createElement('p');
  info.textContent = 'Проверяется сохранённая папка, наличие инструментов и недавняя связь с расширением. Файлы не создаются, загрузка не запускается. Права на запись, работу инструментов, вход на сайт и достаточность места проверка не гарантирует.';
  const button = doc.createElement('button'); button.type = 'button'; button.className = 'btn'; button.textContent = 'Проверить условия загрузки';
  const status = doc.createElement('p'); status.setAttribute('role', 'status');
  const list = doc.createElement('ul');
  panel.append(heading, info, button, status, list); parent.prepend(panel);
  let generation = 0, busy = false;
  const changed = () => { ++generation; list.replaceChildren(); status.textContent = 'Папка изменена. Дождитесь сохранения настройки и повторите проверку.'; };
  folder.addEventListener('input', changed); folder.addEventListener('change', changed);
  button.addEventListener('click', async () => {
    if (busy) return;
    busy = true; button.disabled = true; const ticket = ++generation;
    status.textContent = 'Проверяем сохранённые настройки…'; list.replaceChildren();
    const controller = new AbortController(); let timedOut = false;
    const timer = win.setTimeout(() => { timedOut = true; controller.abort(); }, 15000);
    try {
      const response = await fetcher('/api/preflight', { method: 'POST', headers: { 'X-MH': '1' }, signal: controller.signal });
      if (timedOut) throw new Error('Время ожидания истекло; сервер может продолжать проверку. Попробуйте позже.');
      const data = await response.json();
      if (timedOut) throw new Error('Время ожидания истекло; сервер может продолжать проверку. Попробуйте позже.');
      if (!response.ok) throw new Error(typeof data?.error === 'string' && data.error.length <= 200 ? data.error : 'Сервер не выполнил проверку.');
      const lines = describePreflight(data);
      if (ticket !== generation) return;
      if (data.folder !== folder.value.trim()) { changed(); return; }
      for (const line of lines) { const item = doc.createElement('li'); item.textContent = line; list.append(item); }
      status.textContent = 'Проверка завершена. Результат может устареть; он не гарантирует успешную загрузку.';
    } catch (error) {
      if (ticket === generation) status.textContent = timedOut ? 'Время ожидания истекло; сервер может продолжать проверку. Попробуйте позже.' :
        `Проверка не выполнена: ${error?.message || 'нет связи с MediaHub'}`;
    } finally { win.clearTimeout(timer); busy = false; button.disabled = false; }
  });
}
