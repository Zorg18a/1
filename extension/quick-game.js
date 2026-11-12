const APP = 'http://127.0.0.1:8765';

export function isSupportedGameUrl(value) {
  if (typeof value !== 'string' || value.length > 2000 || /[\x00-\x1f]/.test(value)) return false;
  try {
    const u = new URL(value);
    if (u.protocol !== 'https:' || u.username || u.password || u.port) return false;
    if (u.hostname === 'f95zone.to') return !/%2f|%5c/i.test(u.pathname) && /^\/threads\/[^/]*\d+(?:\/|$)/.test(u.pathname);
    if (u.hostname === 'pornolab.net' && u.pathname === '/forum/viewtopic.php') {
      const ids = u.searchParams.getAll('t'); return ids.length === 1 && /^[1-9][0-9]{0,11}$/.test(ids[0]);
    }
    return false;
  } catch { return false; }
}

export async function queueGame(ext, fetcher, url) {
  if (!isSupportedGameUrl(url)) return { ok: false, error: 'unsupported' };
  const store = ext.storage.local;
  try {
    let { token } = await store.get('token');
    if (!token) {
      const hello = await fetcher(APP + '/ext/hello', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: 'Браузер' }),
      });
      if (!hello.ok) return { ok: false, error: 'server' };
      const result = await hello.json();
      if (!result.token) return { ok: false, error: 'pending' };
      token = result.token;
      await store.set({ token });
    }
    const response = await fetcher(APP + '/ext/game/add', {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'X-MH-Token': token },
      body: JSON.stringify({ url }),
    });
    if (response.status === 401) { await store.remove('token'); return { ok: false, error: 'auth' }; }
    if (!response.ok) return { ok: false, error: 'server' };
    const result = await response.json();
    if (result.status !== 'queued' || !Number.isInteger(result.job)) return { ok: false, error: 'server' };
    return { ok: true, job: result.job };
  } catch { return { ok: false, error: 'offline' }; }
}

export async function setupQuickGame(ext, doc = document) {
  const button = doc.querySelector('#quick-game');
  const message = doc.querySelector('#quick-game-message');
  let tabs;
  try { tabs = await ext.tabs.query({ active: true, currentWindow: true }); }
  catch { message.textContent = 'Не удалось прочитать текущую вкладку.'; return; }
  const tab = tabs[0];
  if (!tab || !isSupportedGameUrl(tab.url)) {
    message.textContent = 'Откройте тему игры на f95zone.to или pornolab.net по HTTPS.';
    return;
  }
  button.disabled = false;
  button.addEventListener('click', async () => {
    button.disabled = true;
    message.textContent = 'Отправляю…';
    const result = await queueGame(ext, fetch, tab.url);
    if (result.ok) {
      let awake = true;
      try { await ext.runtime.sendMessage({ type: 'wake' }); } catch { awake = false; }
      message.textContent = awake ? 'Карточка в очереди. Результат и ошибки — в «Загрузках» MediaHub.' :
        'Карточка в очереди, но фоновую службу не удалось запустить. Проверьте расширение и «Загрузки».';
      return;
    }
    const errors = {
      pending: 'Разрешите расширение в MediaHub, затем нажмите кнопку ещё раз.',
      auth: 'Подключение отозвано. Нажмите ещё раз, чтобы подключить расширение.',
      unsupported: 'Эта страница не поддерживается.',
      server: 'MediaHub отклонил запрос. Проверьте приложение.',
      offline: 'MediaHub недоступен. Запустите приложение и повторите.',
    };
    message.textContent = errors[result.error] || errors.server;
    button.disabled = false;
    if (result.error === 'pending') {
      try { await ext.tabs.create({ url: APP + '/#inbox' }); } catch { /* Откройте MediaHub вручную. */ }
    }
  });
}

if (typeof document !== 'undefined') setupQuickGame(globalThis.browser || globalThis.chrome);
