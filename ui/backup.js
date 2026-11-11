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
}

export function setupBackup({ doc = document, win = window, fetcher = fetch } = {}) {
  const parent = doc.querySelector('#v-settings .set');
  if (!parent) return;
  const panel = doc.createElement('section'); panel.className = 'sg';
  const heading = doc.createElement('h2'); heading.textContent = 'Резервная копия базы';
  const info = doc.createElement('p');
  info.textContent = 'Скачивается только база библиотеки (до 64 МиБ). Медиафайлы, сохранения игр, настройки, расширения и позиции плеера из браузера в копию не входят. Файл может содержать личные данные; храните его в безопасном месте. Восстановление в приложении пока недоступно.';
  const button = doc.createElement('button'); button.type = 'button'; button.className = 'btn'; button.textContent = 'Скачать копию базы';
  const status = doc.createElement('p'); status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');
  panel.append(heading, info, button, status); parent.prepend(panel);
  let busy = false;
  button.addEventListener('click', async () => {
    if (busy) return;
    busy = true; button.disabled = true; status.textContent = 'Подготовка и проверка копии…';
    try {
      await downloadBackup({ fetcher, doc, win });
      status.textContent = 'Файл передан браузеру. Проверьте загрузки и сохраните копию в безопасном месте.';
    } catch (error) {
      status.textContent = `Не удалось скачать копию: ${error?.message || 'ошибка браузера'}`;
    } finally { busy = false; button.disabled = false; }
  });
}
