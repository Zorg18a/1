const GIB = 1024 ** 3;

export function gameLabels(game) {
  const labels = [...(game.genres || []), ...(game.tags || []), game.engine || ''];
  const unique = new Map();
  for (const label of labels) {
    if (typeof label !== 'string' || !label.trim()) continue;
    const value = label.trim();
    if (!unique.has(value.toLowerCase())) unique.set(value.toLowerCase(), value);
  }
  return [...unique.values()];
}

export function sizeMatches(size, filter) {
  const bytes = Number(size) || 0;
  if (filter === 'unknown') return bytes <= 0;
  if (filter === 'small') return bytes > 0 && bytes < GIB;
  if (filter === 'medium') return bytes >= GIB && bytes < 10 * GIB;
  if (filter === 'large') return bytes >= 10 * GIB;
  return true;
}

export function releaseTime(value) {
  const text = String(value || '').trim();
  const m = /^(\d{1,2})[.](\d{1,2})[.](\d{4})$/.exec(text);
  if (m) {
    const time = Date.UTC(Number(m[3]), Number(m[2]) - 1, Number(m[1]));
    const d = new Date(time);
    return d.getUTCFullYear() === Number(m[3]) && d.getUTCMonth() === Number(m[2]) - 1 &&
      d.getUTCDate() === Number(m[1]) ? time : -Infinity;
  }
  if (!text) return -Infinity;
  const time = Date.parse(text);
  return Number.isNaN(time) ? -Infinity : time;
}

export function compareGames(a, b, mode) {
  const update = Number(Boolean(b.g.update)) - Number(Boolean(a.g.update));
  if (update) return update;
  const title = () => String(a.title || '').localeCompare(String(b.title || ''), 'ru');
  let result = 0;
  if (mode === 'added') result = (Number(b.g.added) || 0) - (Number(a.g.added) || 0);
  if (mode === 'size') result = (Number(b.size) || 0) - (Number(a.size) || 0);
  if (mode === 'release') {
    const left = releaseTime(a.g.release), right = releaseTime(b.g.release);
    result = left === right ? 0 : right > left ? 1 : -1;
  }
  return result || title();
}

export function setupGameLibrary() {
  const sort = document.getElementById('gso'), size = document.getElementById('gsize');
  try {
    const saved = JSON.parse(localStorage.getItem('mediahub.game-view') || '{}');
    for (const [select, value] of [[sort, saved.sort], [size, saved.size]]) {
      if ([...select.options].some(option => option.value === value)) select.value = value;
    }
  } catch { /* Browser storage can be unavailable. */ }
  const persist = () => {
    try { localStorage.setItem('mediahub.game-view', JSON.stringify({ sort: sort.value, size: size.value })); }
    catch { /* The view still works for this session. */ }
  };
  sort.addEventListener('change', persist);
  size.addEventListener('change', persist);
  window.MediaHubGameLibrary = { gameLabels, sizeMatches, compareGames };
  window.dispatchEvent(new Event('mediahub:game-library-ready'));
}
