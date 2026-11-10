import { readPreferences } from './preferences.js';

const KEY = 'mh.reader';
export const FITS = Object.freeze(['width', 'height', 'orig']);
const labels = { width: 'По ширине', height: 'По высоте', orig: 'Исходный размер' };

export function clampZoom(value) {
  return typeof value === 'number' && Number.isFinite(value)
    ? Math.min(200, Math.max(50, Math.round(value / 10) * 10)) : 100;
}

export function normalizeReaderPrefs(value) {
  const p = value && typeof value === 'object' ? value : {};
  return { fit: FITS.includes(p.fit) ? p.fit : 'width', zoom: clampZoom(p.zoom) };
}

export function loadReaderPrefs(storage) {
  try { return normalizeReaderPrefs(JSON.parse(storage.getItem(KEY) || '{}')); }
  catch { return normalizeReaderPrefs({}); }
}

export function saveReaderPrefs(storage, value) {
  try { storage.setItem(KEY, JSON.stringify(normalizeReaderPrefs(value))); return true; }
  catch { return false; }
}

export function setupReaderModes({ doc, win, storage, announce, changeChapter }) {
  const view = doc.getElementById('v');
  const zoom = doc.getElementById('reader-zoom');
  const warning = doc.getElementById('reader-storage-warning');
  const radios = [...doc.querySelectorAll('input[name="reader-fit"]')];
  const help = doc.getElementById('reader-help');
  let prefs = loadReaderPrefs(storage);

  function apply() {
    view.dataset.fit = prefs.fit;
    view.style.setProperty('--reader-scale', String(prefs.zoom / 100));
    zoom.textContent = `${prefs.zoom} %`;
    for (const radio of radios) radio.checked = radio.value === prefs.fit;
  }
  function change(next) {
    prefs = normalizeReaderPrefs({ ...prefs, ...next });
    apply();
    warning.hidden = saveReaderPrefs(storage, prefs);
  }
  function fit(value) {
    change({ fit: value });
    announce(labels[prefs.fit]);
  }
  function showHelp() {
    if (help.open) return;
    if (typeof help.showModal === 'function') help.showModal();
    else help.setAttribute('open', '');
  }
  for (const radio of radios) radio.addEventListener('change', () => { if (radio.checked) fit(radio.value); });
  doc.getElementById('reader-less').addEventListener('click', () => change({ zoom: prefs.zoom - 10 }));
  doc.getElementById('reader-more').addEventListener('click', () => change({ zoom: prefs.zoom + 10 }));
  doc.getElementById('reader-help-open').addEventListener('click', showHelp);
  doc.getElementById('reader-help-close').addEventListener('click', () => {
    if (typeof help.close === 'function') help.close(); else help.removeAttribute('open');
  });
  win.addEventListener('keydown', event => {
    if (!readPreferences(storage).hotkeys || event.ctrlKey || event.altKey || event.metaKey || help.open) return;
    const target = event.target;
    if (target?.isContentEditable || target?.closest?.('input,textarea,select,button,a,[contenteditable]:not([contenteditable="false"])')) return;
    const key = event.key.toLowerCase();
    if ((key === 'arrowleft' || key === 'arrowright') && prefs.fit === 'orig' && view.scrollWidth > view.clientWidth + 1) return;
    if (key === 'arrowleft' || key === 'p') { if (!changeChapter(-1)) return; }
    else if (key === 'arrowright' || key === 'n') { if (!changeChapter(1)) return; }
    else if (key === '+' || key === '=') change({ zoom: prefs.zoom + 10 });
    else if (key === '-') change({ zoom: prefs.zoom - 10 });
    else if (key === '0') change({ zoom: 100 });
    else if (key === 'w') fit('width');
    else if (key === 'h') fit('height');
    else if (key === 'o') fit('orig');
    else if (key === '?') showHelp();
    else return;
    event.preventDefault();
  });
  apply();
}
