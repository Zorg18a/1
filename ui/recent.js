// Opening history is local to this origin, not playback/reading progress.
const KEY = 'mediahub.recent.v1';
const LIMIT = 12;
const hash = value => typeof value === 'string' && /^[0-9a-f]{64}$/.test(value);
const idValid = id => typeof id === 'string' && /^[1-9][0-9]{0,18}$/.test(id) && BigInt(id) <= 9223372036854775807n;
const kindValid = kind => ['video', 'audio', 'manga'].includes(kind);

export function readRecent(storage) {
  try {
    const raw = storage.getItem(KEY);
    if (!raw) return [];
    if (raw.length > 10000) return [];
    const value = JSON.parse(raw);
    if (!Array.isArray(value)) return [];
    const seen = new Set(), result = [];
    for (const entry of value.slice(0, LIMIT)) {
      if (!entry || !idValid(entry.id) || !kindValid(entry.kind) || !hash(entry.identity) || seen.has(entry.id)) continue;
      seen.add(entry.id); result.push({ id: entry.id, kind: entry.kind, identity: entry.identity });
    }
    return result;
  } catch { return []; }
}

async function lookup(fetcher, id) {
  const response = await fetcher('/api/recent/' + id, { cache: 'no-store' });
  if (!response.ok) return null;
  const item = await response.json();
  return item && item.id === id && kindValid(item.kind) && hash(item.identity) && hash(item.live_identity) &&
    typeof item.title === 'string' ? item : null;
}

export async function recordRecent({ storage, fetcher, id, kind, liveIdentity }) {
  if (!idValid(id) || !kindValid(kind) || !hash(liveIdentity)) return false;
  try {
    const item = await lookup(fetcher, id);
    if (!item || item.kind !== kind || item.live_identity !== liveIdentity) return false;
    const entries = [{ id, kind, identity: item.identity }, ...readRecent(storage).filter(entry => entry.id !== id)].slice(0, LIMIT);
    storage.setItem(KEY, JSON.stringify(entries));
    return true;
  } catch { return false; }
}

// A history button passes the freshly validated view identity to the destination.
export function expectedRecentIdentity(search) {
  const params = new URLSearchParams(search);
  if (!params.has('recent')) return null;
  const values = params.getAll('recent');
  return values.length === 1 && hash(values[0]) ? values[0] : '';
}

export function setupRecent({ doc, win, storage, fetcher }) {
  const section = doc.createElement('section');
  section.setAttribute('aria-labelledby', 'recent-heading');
  const heading = doc.createElement('h2'); heading.id = 'recent-heading'; heading.textContent = 'Недавно открыто';
  const hint = doc.createElement('p'); hint.className = 'mu';
  hint.textContent = 'История открытий только в этом браузере; это не синхронизация и не гарантия сохранения позиции.';
  const status = doc.createElement('p'); status.className = 'mu'; status.setAttribute('role', 'status');
  const list = doc.createElement('div');
  const clear = doc.createElement('button'); clear.type = 'button'; clear.className = 'btn'; clear.textContent = 'Очистить историю открытий';
  section.append(heading, hint, status, list, clear);
  doc.getElementById('lib').before(section);
  let generation = 0;
  async function refresh() {
    const ticket = ++generation;
    let storageAvailable = true;
    try { storage.getItem(KEY); } catch { storageAvailable = false; }
    const entries = readRecent(storage);
    const results = await Promise.all(entries.map(async entry => {
      try {
        const item = await lookup(fetcher, entry.id);
        return item && item.kind === entry.kind && item.identity === entry.identity ? item : null;
      } catch { return null; }
    }));
    if (ticket !== generation) return;
    list.replaceChildren();
    const available = results.filter(Boolean);
    status.textContent = !storageAvailable ? 'История открытий недоступна в этом браузере.' :
      available.length ? '' : 'Нет доступных недавно открытых материалов.';
    for (const item of available) {
      const button = doc.createElement('button'); button.type = 'button'; button.className = 'btn';
      button.style.maxWidth = '100%'; button.style.overflowWrap = 'anywhere';
      button.textContent = `${item.kind === 'manga' ? 'Читалка' : 'Плеер'}: ${item.title}`;
      button.addEventListener('click', async () => {
        button.disabled = true;
        try {
          const current = await lookup(fetcher, item.id);
          if (ticket !== generation) return;
          const stillSaved = readRecent(storage).some(entry => entry.id === item.id && entry.kind === item.kind && entry.identity === item.identity);
          if (!stillSaved || !current || current.kind !== item.kind || current.identity !== item.identity) {
            status.textContent = 'Материал изменился или недоступен. Обновите историю.'; return;
          }
          win.location.assign(`/${current.kind === 'manga' ? 'm' : 'p'}/${current.id}?recent=${current.live_identity}`);
        } catch { status.textContent = 'Не удалось проверить материал. Попробуйте ещё раз.'; }
        finally { button.disabled = false; }
      });
      list.append(button);
    }
  }
  clear.addEventListener('click', () => {
    ++generation;
    try { storage.removeItem(KEY); list.replaceChildren(); status.textContent = 'История открытий очищена в этом браузере.'; }
    catch { status.textContent = 'Не удалось очистить историю в этом браузере.'; }
  });
  win.addEventListener('storage', event => { if (event.key === KEY || event.key === null) refresh(); });
  win.addEventListener('pageshow', event => { if (event.persisted) refresh(); });
  refresh();
}
