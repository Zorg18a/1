// Local browser-only preview progress. No DB migration or cross-tab ordering.
const MAX_SECONDS = 10 * 365 * 24 * 60 * 60;
const validNumber = value => typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= MAX_SECONDS;
const validDuration = value => validNumber(value) && value > 0;

export function setupPlayerProgress({ media, storage, itemId, identity, status, reset, win }) {
  const key = `mediahub.player.position.v1.${itemId}`;
  let ready = false, started = false, lastWrite = 0, available = /^[0-9a-f]{64}$/.test(identity || '');
  const warning = 'Не удалось прочитать или сохранить позицию в браузере. Проверьте настройки хранения.';
  const unavailable = () => { status.textContent = warning; };
  const recovered = () => { if (status.textContent === warning) status.textContent = ''; };
  if (!available) status.textContent = 'Позиция недоступна: не удалось определить файл.';
  if (!storage) { available = false; unavailable(); }

  function remove() {
    if (!available) return false;
    try { storage.removeItem(key); recovered(); return true; }
    catch { unavailable(); return false; }
  }
  function save() {
    if (!available || !ready || !started || !validDuration(media.duration) || !validNumber(media.currentTime)) return;
    if (media.ended || media.currentTime < 1 || media.currentTime >= media.duration) { remove(); return; }
    try {
      storage.setItem(key, JSON.stringify({ identity, position: media.currentTime, duration: media.duration }));
      lastWrite = Date.now(); recovered();
    } catch { unavailable(); }
  }
  media.addEventListener('loadedmetadata', () => {
    if (ready || !validDuration(media.duration)) return;
    ready = true; reset.disabled = false;
    if (!available) return;
    try {
      const raw = storage.getItem(key);
      if (!raw || raw.length > 2048) return;
      const saved = JSON.parse(raw);
      if (saved?.identity === identity && validNumber(saved.position) && saved.position >= 1 &&
          validDuration(saved.duration) && Math.abs(saved.duration - media.duration) <= 1 &&
          saved.position < media.duration - 0.25) {
        media.currentTime = saved.position;
        status.textContent = 'Позиция восстановлена из этого браузера.';
      }
    } catch { unavailable(); }
  });
  media.addEventListener('play', () => { started = true; });
  media.addEventListener('timeupdate', () => { if (Date.now() - lastWrite >= 5000) save(); });
  media.addEventListener('pause', save);
  media.addEventListener('seeked', () => { started = true; save(); });
  media.addEventListener('ended', () => { started = false; remove(); });
  win.addEventListener('pagehide', save);
  reset.addEventListener('click', () => {
    if (!ready) return;
    try { media.currentTime = 0; started = true; if (remove()) status.textContent = 'Позиция сброшена в этом браузере.'; }
    catch { status.textContent = 'Не удалось перейти к началу файла.'; }
  });
}
