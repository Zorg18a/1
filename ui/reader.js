import { readPreferences } from './preferences.js';
import { setupReaderModes } from './reader-modes.js';
import { setupReaderImage } from './reader-images.js';
import { createProgressSaver, sendProgress, setupProgressConflict } from './reader-progress.js';

const $ = id => document.getElementById(id);
const id = location.pathname.split('/')[2];
let storage;
try { storage = window.localStorage; } catch { storage = null; }
const display = readPreferences(storage);
for (const key of ['theme', 'size', 'contrast']) document.documentElement.dataset[key] = display[key];
const view = $('v');
let manga, current = 0, timer, requestNumber = 0, snapshot, resolvingConflict = false;
const announce = text => { $('reader-announcement').textContent = text; };
const warnBeforeLeave = event => { event.preventDefault(); event.returnValue = true; };
const conflict = setupProgressConflict({ doc: document, itemId: id, getSlug: () => manga?.progress_slug,
  getIdentity: () => manga?.progress_identity, getChapters: () => manga?.chapters, confirm: text => window.confirm(text),
  onResolve: (next, position) => {
    if (timer !== undefined) { clearTimeout(timer); timer = undefined; save(); }
    return progress.resolveConflict(position, () => { snapshot = next; resolvingConflict = true; });
  },
  onStart: () => { view.focus({ preventScroll: true }); $('reader-progress-status').textContent = 'Сохранение выбранной позиции…'; },
});
const progress = createProgressSaver({ onPending: position => conflict.update(position), send: async position => {
  snapshot = await sendProgress({ ...position, snapshot, identity: manga.progress_identity });
}, onDirty: dirty => {
  window[dirty ? 'addEventListener' : 'removeEventListener']('beforeunload', warnBeforeLeave);
}, status: state => {
  const retry = $('reader-progress-retry'), message = $('reader-progress-status');
  if (state === 'unknown') {
    resolvingConflict = false;
    message.textContent = 'Не удалось подтвердить сохранение. Запрос мог выполниться; при повторе старый запрос может завершиться позже.';
    retry.hidden = false;
  } else if (state === 'conflict') {
    resolvingConflict = false;
    if (document.activeElement === retry) view.focus({ preventScroll: true });
    retry.hidden = true;
    message.textContent = 'Запись или позиция манги изменилась либо ключ позиции конфликтует. Последнее сохранение отклонено; подробности ниже.';
    conflict.show();
  } else if (state === 'saved') {
    const recovering = !retry.hidden || resolvingConflict;
    resolvingConflict = false;
    if (document.activeElement === retry) view.focus({ preventScroll: true });
    retry.hidden = true;
    message.textContent = recovering ? 'Позиция сохранена.' : '';
  } else if (state === 'saving' && !retry.hidden) message.textContent = 'Сохранение позиции…';
  else if (state === 'dirty' && retry.hidden) message.textContent = '';
}});
$('reader-progress-retry').addEventListener('click', () => progress.retry());
const canRead = () => typeof manga?.image_identity === 'string' && /^[0-9a-f]{64}$/.test(manga.image_identity);
const canSave = () => canRead() && manga?.progress_save_allowed === true && typeof manga.progress_slug === 'string' &&
  manga.progress_slug.length > 0 && manga.progress_slug.length <= 1024 && !manga.progress_slug.includes('\0') &&
  typeof snapshot === 'string' && /^[0-9a-f]{64}$/.test(snapshot) &&
  typeof manga.progress_identity === 'string' && /^[0-9a-f]{64}$/.test(manga.progress_identity);

function headerSize() {
  document.documentElement.style.setProperty('--reader-header-height', `${$('reader-header').getBoundingClientRect().height}px`);
}
window.addEventListener('resize', headerSize);
if (window.ResizeObserver) new window.ResizeObserver(headerSize).observe($('reader-header'));
headerSize();

function changeChapter(offset) {
  if (!canRead() || !manga?.chapters[current + offset]) return false;
  openChapter(current + offset, 0, true);
  return true;
}
setupReaderModes({ doc: document, win: window, storage, announce, changeChapter });

function textElement(tag, text, className = '') {
  const element = document.createElement(tag);
  element.textContent = text;
  if (className) element.className = className;
  return element;
}

async function openChapter(index, page = 0, focus = false) {
  const chapter = manga?.chapters[index];
  if (!chapter || !canRead()) return;
  if (timer !== undefined) { clearTimeout(timer); timer = undefined; save(); }
  const ticket = ++requestNumber;
  current = index;
  $('c').value = String(index);
  $('p').disabled = index === 0;
  $('n').disabled = index === manga.chapters.length - 1;
  const heading = textElement('h2', `Глава ${index + 1}: ${chapter.label}`, 'reader-chapter');
  heading.tabIndex = -1;
  view.replaceChildren(heading);
  if (focus) {
    heading.focus({ preventScroll: true });
    announce(`Глава ${index + 1} из ${manga.chapters.length}`);
  }
  const files = Array.isArray(chapter.files) ? chapter.files : [];
  page = Math.max(0, Math.min(Number.isFinite(+page) ? Math.floor(+page) : 0, Math.max(0, files.length - 1)));
  const images = files.map((file, number) => {
    const image = document.createElement('img');
    image.dataset.i = String(number);
    image.alt = `Страница ${number + 1}`;
    if (number > page + 1) image.loading = 'lazy';
    image.addEventListener('load', () => {
      if (image.naturalWidth) image.style.setProperty('--natural-width', `${image.naturalWidth}px`);
    });
    const src = `/mi/${encodeURIComponent(id)}/${encodeURIComponent(chapter.id)}/${encodeURIComponent(file)}?identity=${manga.image_identity}`;
    const error = setupReaderImage({ doc: document, image, number: number + 1, src });
    view.append(image, error);
    image.src = src;
    return image;
  });
  const message = files.length
    ? (chapter.done ? 'Конец главы' : `Скачано ${files.length} из ${chapter.expected} стр.`)
    : `Глава «${chapter.label}» ещё не скачана. Запустите загрузку тайтла ещё раз: готовые главы пропускаются, докачаются недостающие.`;
  view.append(textElement('p', message, 'mu'));
  const next = textElement('button', 'Следующая глава ▶');
  next.type = 'button';
  next.disabled = index === manga.chapters.length - 1;
  next.addEventListener('click', () => changeChapter(1));
  view.append(next);
  if (focus && images.length && canSave()) progress.submit({ id, cid: chapter.id, page, slug: manga.progress_slug });
  if (images.length) {
    await Promise.all(images.slice(0, page + 1).map(image =>
      typeof image.decode === 'function' ? image.decode().catch(() => {}) : Promise.resolve()));
  }
  if (ticket !== requestNumber) return;
  const target = focus && page === 0 ? heading : (images[page] || heading);
  target.scrollIntoView();
}

function save() {
  if (!manga?.chapters[current]) return;
  const images = [...view.querySelectorAll('img')];
  if (!images.length) { $('s').textContent = ''; return; }
  let page = images.findIndex(image => image.getBoundingClientRect().bottom > $('reader-header').getBoundingClientRect().height);
  if (page < 0) page = images.length - 1;
  $('s').textContent = `стр. ${page + 1}/${images.length}`;
  if (canSave()) progress.submit({ id, cid: manga.chapters[current].id, page, slug: manga.progress_slug });
}
window.addEventListener('scroll', () => {
  if (!manga?.chapters[current] || !view.querySelectorAll('img').length) return;
  if (canSave()) progress.markDirty();
  clearTimeout(timer);
  timer = setTimeout(() => { timer = undefined; save(); }, 700);
});
$('c').addEventListener('change', event => openChapter(+event.target.value, 0, true));
$('p').addEventListener('click', () => changeChapter(-1));
$('n').addEventListener('click', () => changeChapter(1));

async function load() {
  try {
    const response = await fetch('/api/manga/' + encodeURIComponent(id));
    const data = await response.json();
    if (!response.ok || data.error || !Array.isArray(data.chapters)) throw new Error('not found');
    manga = data;
    snapshot = data.progress_snapshot;
    if (!canRead()) {
      $('reader-error').textContent = 'Страницы не загружаются: идентичность записи не проверена. Обновите читалку и проверьте данные библиотеки.';
      $('c').disabled = $('p').disabled = $('n').disabled = true;
      return;
    }
    if (!canSave()) $('reader-error').textContent = 'Позиция не сохраняется: данные записи, манифеста или снимка позиции не проверены. Проверьте данные библиотеки.';
    document.title = data.title;
    $('t').textContent = `${data.title} · скачано глав ${data.have} из ${data.total || data.have}`;
    $('c').replaceChildren(...data.chapters.map((chapter, index) => {
      const option = textElement('option', `${chapter.files?.length ? (chapter.done ? '✓ ' : '◐ ') : '○ '}${chapter.label}`);
      option.value = String(index);
      return option;
    }));
    if (!data.chapters.length) { view.textContent = 'Нет доступных глав'; return; }
    let index = data.chapters.findIndex(chapter => chapter.files?.length), page = 0;
    if (data.progress) {
      const found = data.chapters.findIndex(chapter => String(chapter.id) === String(data.progress.cid));
      if (found >= 0) { index = found; page = data.progress.page; }
    }
    await openChapter(Math.max(0, index), page);
  } catch {
    $('reader-error').textContent = 'Не удалось открыть тайтл. Проверьте наличие файлов и подключение к MediaHub, затем обновите страницу.';
  }
}
load();
