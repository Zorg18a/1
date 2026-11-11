const MAX_BYTES = 64 * 1024 * 1024;

export async function downloadBackup({ fetcher, doc, win }) {
  const response = await fetcher('/api/backup', { method: 'POST', headers: { 'X-MH': '1' } });
  if (!response.ok) {
    let message;
    try { message = (await response.json())?.error; } catch { /* non-JSON error */ }
    throw new Error(typeof message === 'string' && message.length <= 300 ? message : 'Сервер не подготовил копию.');
  }
  if ((response.headers.get('content-type') || '').split(';')[0].trim().toLowerCase() !== 'application/vnd.sqlite3') {
    throw new Error('Сервер вернул неожиданный формат.');
  }
  const length = response.headers.get('content-length') || '';
  if (!/^[0-9]+$/.test(length) || Number(length) < 100 || Number(length) > MAX_BYTES) throw new Error('Некорректный размер копии.');
  const sha256 = response.headers.get('x-backup-sha256') || '';
  if (!/^[0-9a-f]{64}$/.test(sha256)) throw new Error('Сервер не вернул отпечаток копии.');
  const blob = await response.blob();
  if (blob.size !== Number(length)) throw new Error('Копия передана не полностью.');
  const header = new Uint8Array(await blob.slice(0, 16).arrayBuffer());
  if (Array.from(header, x => String.fromCharCode(x)).join('') !== 'SQLite format 3\0') throw new Error('Неверный формат копии.');
  const url = win.URL.createObjectURL(blob);
  const link = doc.createElement('a');
  try {
    const stamp = new Date().toISOString().replace(/[-:.]/g, '');
    link.href = url; link.download = `mediahub-library-${stamp}.db`;
    doc.body.append(link); link.click();
  } catch (error) {
    win.URL.revokeObjectURL(url);
    throw error;
  } finally { link.remove(); }
  // A browser download may continue after click returns; do not revoke immediately.
  win.setTimeout(() => win.URL.revokeObjectURL(url), 60000);
  return sha256;
}

export async function inspectBackup(file, fetcher = fetch) {
  if (!file) throw new Error('Сначала выберите файл копии.');
  if (!Number.isSafeInteger(file.size) || file.size < 100 || file.size > MAX_BYTES) throw new Error('Размер файла должен быть от 100 байт до 64 МиБ.');
  let response;
  try {
    response = await fetcher('/api/backup/inspect', { method: 'POST', headers: {
      'X-MH': '1', 'Content-Type': 'application/octet-stream',
    }, body: file });
  } catch { throw new Error('Нет связи с MediaHub.'); }
  let result;
  try { result = await response.json(); } catch { throw new Error('Сервер вернул некорректный ответ.'); }
  if (!response.ok) throw new Error(typeof result?.error === 'string' && result.error.length <= 300 ? result.error : 'Проверка не выполнена.');
  if (result?.ok !== 1 || !Number.isSafeInteger(result.items) || result.items < 0 ||
      !Number.isSafeInteger(result.progress) || result.progress < 0 ||
      typeof result.sha256 !== 'string' || !/^[0-9a-f]{64}$/.test(result.sha256)) throw new Error('Сервер вернул некорректный ответ.');
  return result;
}

export function setupBackup({ doc = document, win = window, fetcher = fetch } = {}) {
  const parent = doc.querySelector('#v-settings .set');
  if (!parent) return;
  const panel = doc.createElement('section'); panel.className = 'sg';
  const heading = doc.createElement('h2'); heading.textContent = 'Резервная копия базы';
  const info = doc.createElement('p');
  info.textContent = 'Скачивается только база библиотеки (до 64 МиБ). Медиафайлы, сохранения игр, настройки, расширения и позиции плеера из браузера в копию не входят. Файл может содержать личные данные; храните его в безопасном месте. Восстановление в приложении пока недоступно. Сохраните отпечаток SHA-256 отдельно и сравните с отпечатком выбранного файла при проверке. Совпадение не подтверждает подлинность и пригодность для восстановления.';
  const button = doc.createElement('button'); button.type = 'button'; button.className = 'btn'; button.textContent = 'Скачать копию базы';
  const status = doc.createElement('p'); status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');
  status.setAttribute('style', 'overflow-wrap:anywhere');
  const label = doc.createElement('label'); label.htmlFor = 'backup-file'; label.textContent = 'Файл копии для проверки';
  const file = doc.createElement('input'); file.type = 'file'; file.id = 'backup-file'; file.accept = '.db,.sqlite,.sqlite3';
  file.setAttribute('style', 'display:block;max-width:100%;margin:8px 0');
  const verify = doc.createElement('button'); verify.type = 'button'; verify.className = 'btn'; verify.textContent = 'Проверить копию';
  const report = doc.createElement('p'); report.setAttribute('role', 'status'); report.setAttribute('aria-live', 'polite');
  report.setAttribute('style', 'overflow-wrap:anywhere');
  panel.append(heading, info, button, status, label, file, verify, report); parent.prepend(panel);
  let checking = false;
  file.addEventListener('change', () => { report.textContent = ''; });
  verify.addEventListener('click', async () => {
    if (checking) return;
    checking = true; verify.disabled = true; file.disabled = true; report.textContent = 'Проверка выбранного файла…';
    try {
      const result = await inspectBackup(file.files?.[0], fetcher);
      report.textContent = `Целостность и минимальная структура проверены: материалов ${result.items}, позиций манги ${result.progress}. SHA-256 проверенного файла: ${result.sha256}. Сравните с сохранённым отпечатком вручную. Совместимость и медиафайлы не проверены; восстановление не выполнялось.`;
    } catch (error) { report.textContent = `Проверка не выполнена: ${error?.message || 'ошибка браузера'}`; }
    finally { checking = false; verify.disabled = false; file.disabled = false; }
  });
  let busy = false;
  button.addEventListener('click', async () => {
    if (busy) return;
    busy = true; button.disabled = true; status.textContent = 'Подготовка и проверка копии…';
    try {
      const sha256 = await downloadBackup({ fetcher, doc, win });
      status.textContent = `Файл передан браузеру. Проверьте загрузки и сохраните копию в безопасном месте. SHA-256 подготовленной копии: ${sha256}. Сохраните отпечаток отдельно и проверьте сохранённый файл.`;
    } catch (error) {
      status.textContent = `Не удалось скачать копию: ${error?.message || 'ошибка браузера'}`;
    } finally { busy = false; button.disabled = false; }
  });
}
