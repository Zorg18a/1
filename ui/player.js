import { readPreferences } from './preferences.js';
import { setupPlayerKeys } from './player-keys.js';
import { setupSubtitleSelector } from './player-subtitles.js';
import { setupPlayerProgress } from './player-progress.js';
import { expectedRecentIdentity, recordRecent } from './recent.js';

const $ = id => document.getElementById(id);
const id = location.pathname.split('/')[2];
let storage;
try { storage = window.localStorage; } catch { storage = null; }
const preferences = readPreferences(storage);
for (const key of ['theme', 'size', 'contrast']) document.documentElement.dataset[key] = preferences[key];
const help = $('player-help');
const announce = message => { $('player-announcement').textContent = message; };
function showHelp() {
  if (help.open) return;
  if (typeof help.showModal === 'function') help.showModal(); else help.setAttribute('open', '');
}
$('player-help-open').addEventListener('click', showHelp);
$('player-help-close').addEventListener('click', () => {
  if (typeof help.close === 'function') help.close(); else help.removeAttribute('open');
});

function showError(message, direct = '') {
  $('player-error-text').textContent = message;
  $('player-error').hidden = false;
  $('player-direct').hidden = !direct;
  if (direct) $('player-direct').href = direct;
}

async function load() {
  try {
    if (!/^[0-9]{1,19}$/.test(id)) throw new Error('id');
    const number = BigInt(id);
    if (number < 1n || number > 9223372036854775807n) throw new Error('id');
    const itemId = number.toString();
    const response = await fetch('/api/player-preview/' + itemId);
    const item = await response.json();
    if (!response.ok || !['video', 'audio'].includes(item.kind) || item.src !== `/f/${itemId}`) throw new Error('item');
    const recentExpected = expectedRecentIdentity(location.search);
    if (recentExpected !== null && (!recentExpected || item.local_position_identity !== recentExpected)) throw new Error('changed');
    const title = typeof item.title === 'string' ? item.title : 'Материал';
    document.title = `${title} — MediaHub`;
    $('player-title').textContent = title;
    if (item.subtitle_warning) $('player-warning').textContent = 'Не удалось проверить субтитры для этого файла.';
    const container = $('player-container');
    if (item.kind === 'audio' && item.cover === `/t/${itemId}`) {
      const image = document.createElement('img');
      image.id = 'player-cover'; image.alt = ''; image.src = item.cover;
      container.append(image);
    }
    const media = document.createElement(item.kind);
    media.id = 'player-media'; media.controls = true; media.preload = 'metadata';
    media.setAttribute('aria-label', item.kind === 'video' ? 'Видеоплеер' : 'Аудиоплеер');
    media.addEventListener('error', () => showError('Не удалось воспроизвести файл. Возможно, браузер не поддерживает его формат.', item.src));
    const pattern = new RegExp(`^/sub/${itemId}/[0-9]{1,2}\\.vtt\\?rev=[0-9a-f]{32}$`);
    let expected = 0;
    for (const track of Array.isArray(item.subs) ? item.subs : []) {
      if (typeof track.url !== 'string' || !pattern.test(track.url) || typeof track.lang !== 'string' || !/^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8}){0,3}$/.test(track.lang)) continue;
      const node = document.createElement('track');
      node.kind = 'subtitles'; node.srclang = track.lang; node.label = String(track.label || track.lang); node.src = track.url;
      node.addEventListener('error', () => { $('player-warning').textContent = 'Не удалось загрузить дорожку субтитров. Попробуйте другую или обновите страницу.'; });
      media.append(node); expected++;
    }
    setupPlayerProgress({ media, storage, itemId, identity: item.local_position_identity,
      status: $('player-progress-status'), reset: $('player-restart'), win: window });
    media.src = item.src;
    container.append(media);
    void recordRecent({ storage, fetcher: fetch, id: itemId, kind: item.kind, liveIdentity: item.local_position_identity });
    if (item.kind === 'audio' && expected && !item.subtitle_warning) $('player-warning').textContent = 'Отображение субтитров для аудио зависит от браузера.';
    const subtitlesChanged = setupSubtitleSelector({ doc: document, media, container: $('player-subtitle-control'),
      select: $('player-subtitles'), storage, itemId, expected });
    setupPlayerKeys({ doc: document, win: window, media, storage, announce, showHelp, subtitlesChanged });
  } catch {
    showError('Материал не найден или недоступен.');
  }
}
load();
