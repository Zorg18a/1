// MediaHub: фоновая часть расширения. Передаёт выбранные вкладки приложению и закрывает вкладки, когда приложение скажет, что материал скачан.
// Расширение видит только адрес и название вкладок, которые вы сами отправили. Пароли, cookies, история и закладки не читаются.
const ext = globalThis.browser || globalThis.chrome;      // Firefox: browser, Chrome и Edge: chrome
const APP = 'http://127.0.0.1:8765';
const store = ext.storage.local;
const sleep = ms => new Promise(r => setTimeout(r, ms));
const browserName = () => (navigator.userAgent.includes('Firefox/') ? 'Firefox' : navigator.userAgent.includes('Edg/') ? 'Edge' : 'Chrome');

async function call(path, body) {
  const { token } = await store.get('token');
  const r = await fetch(APP + path, {
    method: body === undefined ? 'GET' : 'POST',
    headers: { 'Content-Type': 'application/json', ...(token ? { 'X-MH-Token': token } : {}) },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (r.status === 401) { await store.remove('token'); throw new Error('auth'); }
  return r.json();
}

// Знакомство с приложением: токен выдаётся только после того, как человек нажал «Разрешить» в MediaHub.
async function ensurePaired() {
  const { token } = await store.get('token');
  if (token) return 'ok';
  const r = await fetch(APP + '/ext/hello', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: browserName() }) });
  const j = await r.json();
  if (j.token) { await store.set({ token: j.token }); return 'ok'; }
  return 'pending';
}

async function openApp(hash) {
  const url = APP + '/#' + hash;
  const tabs = await ext.tabs.query({ url: APP + '/*' });
  if (tabs.length) { await ext.tabs.update(tabs[0].id, { active: true, url }); await ext.windows.update(tabs[0].windowId, { focused: true }); }
  else await ext.tabs.create({ url });
}

async function sendTabs(m) {
  try {
    let st = await ensurePaired();
    if (st !== 'ok') {
      await openApp('inbox');            // показываем запрос на подключение
      for (let i = 0; i < 30 && st !== 'ok'; i++) { await sleep(2000); st = await ensurePaired(); }
      if (st !== 'ok') { await store.set({ pending: m }); return { ok: false, error: 'pending' }; }
    }
    const r = await call('/ext/tabs', { tabs: m.tabs, close: m.close, browser: m.browser || browserName() });
    await store.remove('pending');
    await openApp('inbox');
    poll();
    return { ok: true, count: r.count };
  } catch (e) {
    await store.set({ pending: m });     // приложение не запущено: список подождёт в расширении (только адреса и названия)
    return { ok: false, error: 'offline' };
  }
}

ext.runtime.onMessage.addListener((m, _s, reply) => {
  if (m.type === 'send') { sendTabs(m).then(reply); return true; } if (m.type === 'wake') { poll(); reply({ ok: true }); }
  return false;
});

// Закрытие вкладок: приложение само решает, когда материал скачан; расширение за 5 секунд предупреждает и даёт отменить.
async function closeBatch(cmds) {
  const live = [];
  for (const c of cmds) {
    let tab = null;
    try { tab = await ext.tabs.get(c.tab_id); } catch (e) {}
    if (!tab) { await call('/ext/ack', { id: c.id, result: 'missing' }); continue; }         // вкладку уже закрыли сами
    try { if (new URL(tab.url).host !== new URL(c.url).host) { await call('/ext/ack', { id: c.id, result: 'moved' }); continue; } } catch (e) {}
    live.push(c);
  }
  if (!live.length) return;
  const nid = 'mh-close-' + Date.now(); let cancelled = false;
  const onBtn = id => { if (id === nid) cancelled = true; };
  try { if (ext.notifications.onButtonClicked) ext.notifications.onButtonClicked.addListener(onBtn); ext.notifications.onClicked.addListener(onBtn); } catch (e) {}
  const base = { type: 'basic', iconUrl: 'icon128.png', title: 'MediaHub',
    message: (live.length === 1 ? `Закрою вкладку «${(live[0].title || '').slice(0, 60)}» через 5 с.` : `Закрою вкладки (${live.length}) через 5 с.`) + ' Нажмите, чтобы отменить.' };
  try { await ext.notifications.create(nid, { ...base, buttons: [{ title: 'Отменить' }] }); }
  catch (e) { try { await ext.notifications.create(nid, base); } catch (e2) {} }       // Firefox: без кнопок
  await sleep(5000);
  try { if (ext.notifications.onButtonClicked) ext.notifications.onButtonClicked.removeListener(onBtn); ext.notifications.onClicked.removeListener(onBtn); } catch (e) {}
  try { ext.notifications.clear(nid); } catch (e) {}
  for (const c of live) {
    if (cancelled) { await call('/ext/ack', { id: c.id, result: 'cancelled' }); continue; }
    try { await ext.tabs.remove(c.tab_id); } catch (e) {}
    let still = true; try { await ext.tabs.get(c.tab_id); } catch (e) { still = false; }   // отвечаем «закрыта» только если вкладки правда нет
    await call('/ext/ack', { id: c.id, result: still ? 'failed' : 'closed' });
  }
  if (!cancelled) try { ext.notifications.create({ type: 'basic', iconUrl: 'icon128.png', title: 'MediaHub',
    message: live.length === 1 ? 'Загрузка завершена. Вкладка закрыта, источник сохранён в библиотеке.' : `Загрузка завершена. Закрыто вкладок: ${live.length}, источники сохранены в библиотеке.` }); } catch (e) {}
}

// ---------- Манга в вашем браузере: расширение открывает сайт в небольшом окне, под вашим входом, и отдаёт приложению список глав и адреса страниц ----------
let wnd = null, lastTask = 0, active = 0, keep = null;
function waitComplete(tabId, ms) {
  return new Promise(res => {
    let done = false;
    const fn = (id, info) => { if (id === tabId && info.status === 'complete') fin(); };
    const fin = () => { if (!done) { done = true; try { ext.tabs.onUpdated.removeListener(fn); } catch (e) {} res(); } };
    ext.tabs.onUpdated.addListener(fn); setTimeout(fin, ms);
  });
}
async function stubOn(site) {   // в скрытом окне браузер не подгружает ленивые картинки: подсказываем странице, что всё на виду (только на время загрузки)
  try { if (ext.scripting && ext.scripting.registerContentScripts) { try { await ext.scripting.unregisterContentScripts({ ids: ['mh-io'] }); } catch (e) {}
    await ext.scripting.registerContentScripts([{ id: 'mh-io', matches: [site + '/*'], js: ['io_stub.js'], runAt: 'document_start', world: 'MAIN', persistAcrossSessions: false }]); } } catch (e) {}
}
async function stubOff() { try { if (ext.scripting && ext.scripting.unregisterContentScripts) await ext.scripting.unregisterContentScripts({ ids: ['mh-io'] }); } catch (e) {} }
async function ensureWindow(url, site) {
  lastTask = Date.now();
  if (wnd) { try { const w = await ext.windows.get(wnd.id, { populate: true }); return w.tabs[0]; } catch (e) { wnd = null; } }
  await stubOn(site);
  wnd = await ext.windows.create({ url, type: 'popup', width: 520, height: 780, focused: false });
  return wnd.tabs[0];
}
async function closeWnd() { const w = wnd; wnd = null; if (w) { try { await ext.windows.remove(w.id); } catch (e) {} } await stubOff(); }
async function navigate(tabId, url) { await ext.tabs.update(tabId, { url }); await waitComplete(tabId, 30000); }
async function runInTab(tabId, func, args) {
  if (ext.scripting && ext.scripting.executeScript) { const r = await ext.scripting.executeScript({ target: { tabId }, func, args: args || [] }); return r && r[0] ? r[0].result : undefined; }
  const r = await ext.tabs.executeScript(tabId, { code: `(${func.toString()}).apply(null, ${JSON.stringify(args || [])})` }); return r && r[0];   // Firefox
}
// Эти функции выполняются внутри страницы сайта.
async function pageList() {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  for (let i = 0; i < 80 && !document.querySelector('article.card-chapter'); i++) await sleep(500);
  if (!document.querySelector('article.card-chapter')) return { error: 'список глав не появился: возможно, нужен вход или проверка «я не робот». Откройте сайт в этом браузере, пройдите её и повторите' };
  const mm = document.body.innerText.match(/Главы\s+(\d+)/), exp = mm ? +mm[1] : 0; let last = -1, calm = 0;
  for (let i = 0; i < 80; i++) {
    const cards = document.querySelectorAll('article.card-chapter'), c = cards.length; calm = c === last ? calm + 1 : 0; last = c;
    if (calm >= (exp && c >= exp ? 2 : 6)) break;
    cards[c - 1].scrollIntoView(); window.scrollTo(0, document.body.scrollHeight); window.dispatchEvent(new Event('scroll'));
    const btn = [...document.querySelectorAll('button')].find(x => /^(показать|загрузить)\s+ещ[её]/i.test(x.textContent.trim())); if (btn) btn.click();
    await sleep(900);
  }
  const po = document.querySelector('.project-poster img'), h1 = document.querySelector('h1');
  const chapters = [...document.querySelectorAll('article.card-chapter')].map(a => { const l = a.querySelector('a.card-chapter__link') || a.querySelector('a'), n = a.querySelector('.card-chapter__name') || a;
    return { url: l.href, cid: (l.href.match(/chapters\/(\d+)/) || [])[1] || '', label: (n.textContent || '').trim() }; });
  return { title: h1 ? h1.textContent.trim() : '', cover: po ? new URL(po.getAttribute('data-zoom-src') || po.src, location.href).href : '', chapters, expected: exp };
}
async function pagePages() {
  const sleep = ms => new Promise(r => setTimeout(r, ms)), ok = s => /^https?:/.test(s || '');
  for (let i = 0; i < 80 && !document.querySelector('.reader-item img'); i++) await sleep(500);
  if (!document.querySelector('.reader-item img')) return { error: 'читалка не открылась (нужен вход?)' };
  const tm = ((document.querySelector('.nav-panel__page span') || {}).textContent || '').match(/\/\s*(\d+)/), total = tm ? +tm[1] : 0;
  if (document.querySelector('.reader-main-vertical')) {   // «Лента»: прокручиваем к первой ещё не загруженной странице
    for (let k = 0; k < 600; k++) { const miss = [...document.querySelectorAll('.reader-item img')].find(i => !ok(i.src)); if (!miss) break; miss.scrollIntoView(); window.dispatchEvent(new Event('scroll')); await sleep(120); }
    const srcs = [...document.querySelectorAll('.reader-item img')].map(i => i.src); return { mode: 'vertical', total: total || srcs.length, srcs };
  }
  const out = [], cur = () => (document.querySelector('.reader-item img') || {}).src;   // «По страницам»: листаем кликом
  for (let k = 1; k <= (total || 1); k++) {
    for (let t = 0; t < 40 && !ok(cur()); t++) await sleep(150);
    if (k > 1) for (let t = 0; t < 30 && cur() === out[out.length - 1]; t++) await sleep(150);
    out.push(cur()); const nx = document.querySelector('.tap-zone__next'); if (!nx || k === total) break; nx.click(); await sleep(300);
  }
  return { mode: 'paged', total, srcs: out };
}
async function onePage() { const sleep = ms => new Promise(r => setTimeout(r, ms)); let s = ''; for (let t = 0; t < 60; t++) { s = (document.querySelector('.reader-item img') || {}).src || ''; if (/^https?:/.test(s)) break; await sleep(150); } return s; }
async function mangaList(p) {
  const tab = await ensureWindow(p.url, p.site); await navigate(tab.id, p.url);
  const r = await runInTab(tab.id, pageList, []); if (!r || r.error) throw new Error((r && r.error) || 'страница не открылась');
  r.ua = navigator.userAgent; return r;
}
async function mangaPages(p) {
  const tab = await ensureWindow(p.url, p.site); await navigate(tab.id, p.url);
  let r = await runInTab(tab.id, pagePages, []); if (!r || r.error) throw new Error((r && r.error) || 'читалка не открылась');
  const bad = r.srcs.some(s => !/^https?:/.test(s || '')) || new Set(r.srcs).size !== r.srcs.length || (r.total && r.srcs.length < r.total);
  if (r.mode === 'paged' && bad && r.total) {     // запасной путь: страница за страницей по адресу
    const out = []; for (let k = 1; k <= r.total; k++) { await navigate(tab.id, p.url.replace(/\/pages\/\d+/, '/pages/' + k)); out.push(await runInTab(tab.id, onePage, [])); }
    r = { mode: 'paged', total: r.total, srcs: out };
  }
  return { pages: r.srcs, total: r.total, mode: r.mode };
}
async function fetchHtml(p) {   // страница игры: сначала обычным запросом под вашим входом, при проверке «я не робот» — через окно браузера
  let html = '', via = 'fetch';
  try { const r = await fetch(p.url, { credentials: 'include' }); if (r.ok) html = await r.text(); } catch (e) {}
  const blocked = !html || /Just a moment|cf-chl|challenge-platform/i.test(html) || !/<meta[^>]+og:title/i.test(html);
  if (blocked) {
    via = 'window'; const tab = await ensureWindow(p.url, p.site || new URL(p.url).origin); await navigate(tab.id, p.url);
    for (let i = 0; i < 40; i++) {      // проверка Cloudflare в обычном браузере обычно проходит сама за несколько секунд: ждём
      await sleep(1000); html = (await runInTab(tab.id, () => document.documentElement.outerHTML, [])) || '';
      if (/<meta[^>]+og:title/i.test(html) && !/<title>\s*Just a moment/i.test(html)) break;
    }
    await closeWnd();
  }
  return { html: html.slice(0, 3000000), via };
}
async function handleTask(t) {
  active++; lastTask = Date.now(); if (!keep) keep = setInterval(() => { try { ext.runtime.getPlatformInfo(); } catch (e) {} }, 20000);   // не даём службе уснуть посреди загрузки
  try {
    let res;
    if (t.type === 'manga_list') res = await mangaList(t.payload);
    else if (t.type === 'manga_pages') res = await mangaPages(t.payload);
    else if (t.type === 'fetch_html') res = await fetchHtml(t.payload);
    else if (t.type === 'manga_done') { await closeWnd(); res = {}; }
    else throw new Error('неизвестное задание');
    await call('/ext/result', { id: t.task, ok: true, data: res });
  } catch (e) { try { await call('/ext/result', { id: t.task, ok: false, error: String((e && e.message) || e).slice(0, 300) }); } catch (e2) {} }
  finally { active--; if (!active && keep) { clearInterval(keep); keep = null; } }
}

let polling = false;
async function poll() {
  if (polling) return; polling = true;
  try {
    const { token } = await store.get('token'); if (!token) return;
    for (let i = 0; i < 12; i++) {                      // длинные запросы: ответ приходит, как только есть что закрыть
      const r = await call('/ext/commands?wait=20'), cmds = r.commands || [];
      for (const t of cmds.filter(c => c.cmd === 'task')) handleTask(t);          // не ждём: задание может идти минуты
      const closes = cmds.filter(c => c.cmd === 'close'); if (closes.length) await closeBatch(closes);
      if (wnd && !active && Date.now() - lastTask > 180000) closeWnd();
    }
  } catch (e) {} finally { polling = false; }
}
async function flushPending() {
  const { pending } = await store.get('pending');
  if (pending) { try { if (await ensurePaired() === 'ok') await sendTabs(pending); } catch (e) {} }
}
const PERIOD = navigator.userAgent.includes('Firefox/') ? 1 : 0.5;
ext.alarms.create('mh-poll', { periodInMinutes: PERIOD });
ext.alarms.onAlarm.addListener(a => { if (a.name === 'mh-poll') { flushPending(); poll(); } });
ext.runtime.onStartup.addListener(poll);
ext.runtime.onInstalled.addListener(() => { ext.alarms.create('mh-poll', { periodInMinutes: PERIOD }); poll(); });
