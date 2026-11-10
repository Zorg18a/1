import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const dataUrl = text => `data:text/javascript;base64,${Buffer.from(text).toString('base64')}`;
const prefSource = await readFile(new URL('../ui/preferences.js', import.meta.url), 'utf8');
const modeSource = (await readFile(new URL('../ui/reader-modes.js', import.meta.url), 'utf8'))
  .replace("'./preferences.js'", `'${dataUrl(prefSource)}'`);
const modeUrl = dataUrl(modeSource);
const modes = await import(modeUrl);
const imageSource = await readFile(new URL('../ui/reader-images.js', import.meta.url), 'utf8');
const imageUrl = dataUrl(imageSource);
const { setupReaderImage } = await import(imageUrl);
const progressUrl = dataUrl(await readFile(new URL('../ui/reader-progress.js', import.meta.url), 'utf8'));

class Element {
  constructor(tag = 'div') {
    this.tagName = tag.toUpperCase(); this.children = []; this.listeners = {}; this.dataset = {};
    this.style = { values: {}, setProperty: (key, value) => { this.style.values[key] = value; } };
    this.value = ''; this.textContent = ''; this.hidden = false; this.open = false;
    this.scrollWidth = 400; this.clientWidth = 400; this.bottom = 100;
  }
  addEventListener(type, handler) { (this.listeners[type] ??= []).push(handler); }
  dispatch(type, event = {}) { for (const handler of this.listeners[type] || []) handler({ target: this, ...event }); }
  setAttribute(name, value) { this[name] = value; }
  append(...elements) { this.children.push(...elements); }
  replaceChildren(...elements) { this.children = elements; }
  querySelectorAll(selector) { return selector === 'img' ? this.children.filter(child => child.tagName === 'IMG') : []; }
  closest() { return null; }
  focus() { this.focused = true; }
  scrollIntoView() { this.scrolled = true; }
  getBoundingClientRect() { return { height: 80, bottom: this.bottom }; }
  decode() { return Promise.resolve(); }
  showModal() { this.open = true; }
  close() { this.open = false; }
}

function fixture() {
  const names = ['v', 'reader-header', 'reader-zoom', 'reader-storage-warning', 'reader-help',
    'reader-less', 'reader-more', 'reader-help-open', 'reader-help-close', 'reader-announcement',
    'reader-error', 'reader-progress-status', 'reader-progress-retry', 't', 'c', 'p', 'n', 's'];
  const elements = Object.fromEntries(names.map(name => [name, new Element()]));
  const radios = ['width', 'height', 'orig'].map(value => Object.assign(new Element('input'), { value }));
  const doc = { documentElement: new Element('html'), getElementById: id => elements[id],
    querySelectorAll: () => radios, createElement: tag => new Element(tag) };
  const win = { listeners: {}, addEventListener(type, handler) { this.listeners[type] = handler; } };
  const data = new Map();
  const storage = { getItem: key => data.get(key) ?? null, setItem: (key, value) => data.set(key, value) };
  return { elements, radios, doc, win, data, storage };
}
function key(win, value, target = new Element('div'), modifiers = {}) {
  let prevented = false;
  win.listeners.keydown({ key: value, target, preventDefault() { prevented = true; }, ...modifiers });
  return prevented;
}
const flush = () => new Promise(resolve => setImmediate(resolve));

test('a failed page offers a keyboard-accessible retry and returns focus on success', () => {
  const doc = { createElement: tag => new Element(tag), activeElement: null };
  const image = new Element('img');
  const panel = setupReaderImage({ doc, image, number: 2, src: '/mi/1/2/002.png' });
  const [message, retry] = panel.children;
  assert.equal(panel.hidden, true);
  assert.equal(message.role, 'status');
  image.dispatch('error');
  assert.equal(panel.hidden, false);
  assert.match(message.textContent, /страницу 2/);
  assert.equal(retry.textContent, 'Повторить загрузку страницы 2');
  doc.activeElement = retry;
  retry.dispatch('click');
  assert.match(image.src, /^\/mi\/1\/2\/002\.png\?retry=\d+-1$/);
  assert.match(message.textContent, /Повторная загрузка/);
  image.dispatch('error');
  assert.equal(panel.hidden, false);
  retry.dispatch('click');
  image.dispatch('load');
  assert.equal(panel.hidden, true);
  assert.equal(message.textContent, '');
  assert.equal(image.focused, true);
  assert.equal(image.tabIndex, -1);
});

test('reader preferences clamp, validate and survive blocked storage', () => {
  assert.deepEqual(modes.normalizeReaderPrefs({ fit: 'bad', zoom: NaN }), { fit: 'width', zoom: 100 });
  assert.equal(modes.clampZoom(54), 50);
  assert.equal(modes.clampZoom(155), 160);
  assert.equal(modes.clampZoom(1000), 200);
  assert.deepEqual(modes.loadReaderPrefs({ getItem() { throw Error('denied'); } }), { fit: 'width', zoom: 100 });
  assert.deepEqual(modes.loadReaderPrefs({ getItem() { return '{'; } }), { fit: 'width', zoom: 100 });
  assert.equal(modes.saveReaderPrefs(null, {}), false);
});

test('modes persist, keys obey settings and horizontal scrolling remains available', () => {
  const f = fixture(); let notice = '', chapter = 0;
  modes.setupReaderModes({ ...f, announce: text => { notice = text; }, changeChapter: n => { chapter += n; return true; } });
  assert.equal(f.elements.v.dataset.fit, 'width');
  f.radios[1].checked = true; f.radios[1].dispatch('change');
  assert.equal(f.elements.v.dataset.fit, 'height');
  assert.equal(notice, 'По высоте');
  f.elements['reader-more'].dispatch('click');
  assert.equal(f.elements['reader-zoom'].textContent, '110 %');
  assert.deepEqual(JSON.parse(f.data.get('mh.reader')), { fit: 'height', zoom: 110 });
  assert.equal(key(f.win, 'o'), true);
  f.elements.v.scrollWidth = 600;
  assert.equal(key(f.win, 'ArrowRight'), false);
  assert.equal(key(f.win, 'n'), true);
  assert.equal(chapter, 1);
  const field = new Element('input'); field.closest = () => field;
  assert.equal(key(f.win, 'n', field), false);
  assert.equal(key(f.win, 'n', new Element(), { ctrlKey: true }), false);
  f.data.set('mediahub.display.v1', JSON.stringify({ hotkeys: false }));
  assert.equal(key(f.win, 'n'), false);
  f.elements['reader-help-open'].dispatch('click');
  assert.equal(f.elements['reader-help'].open, true);
  f.elements['reader-help-close'].dispatch('click');
  assert.equal(f.elements['reader-help'].open, false);
});

test('reader restores page, changes chapter, saves progress and applies display settings', async () => {
  const f = fixture(); const requests = [];
  f.data.set('mediahub.display.v1', JSON.stringify({ theme: 'light', contrast: 'high', hotkeys: true }));
  const previous = Object.fromEntries(['document', 'window', 'location', 'fetch'].map(name => [name, globalThis[name]]));
  try {
    globalThis.document = f.doc; globalThis.window = f.win; f.win.localStorage = f.storage;
    globalThis.location = { pathname: '/m/42' };
    globalThis.fetch = async (url, options) => {
      requests.push({ url, options });
      if (url === '/api/progress') return { ok: true, json: async () => ({ ok: 1 }) };
      return { ok: true, json: async () => ({ title: 'Пример', have: 2, total: 2,
        chapters: [{ id: '1', label: 'Первая', files: ['001.jpg', '002.jpg'], done: true },
          { id: '2', label: '<Вторая>', files: ['001.jpg'], done: true }], progress: { cid: '1', page: 1 } }) };
    };
    const source = (await readFile(new URL('../ui/reader.js', import.meta.url), 'utf8'))
      .replace("'./preferences.js'", `'${dataUrl(prefSource)}'`).replace("'./reader-modes.js'", `'${modeUrl}'`).replace("'./reader-images.js'", `'${imageUrl}'`).replace("'./reader-progress.js'", `'${progressUrl}'`);
    await import(dataUrl(source)); await flush(); await flush();
    const images = f.elements.v.querySelectorAll('img');
    assert.equal(images.length, 2);
    assert.equal(images[1].scrolled, true);
    assert.equal(images[1].src, '/mi/42/1/002.jpg');
    images[1].naturalWidth = 640; images[1].dispatch('load');
    assert.equal(images[1].style.values['--natural-width'], '640px');
    assert.equal(f.doc.documentElement.dataset.theme, 'light');
    assert.equal(f.doc.documentElement.dataset.contrast, 'high');
    images[0].bottom = 40; images[1].bottom = 150;
    f.win.listeners.scroll(); await new Promise(resolve => setTimeout(resolve, 750));
    const post = requests.find(request => request.url === '/api/progress');
    assert.deepEqual(JSON.parse(post.options.body), { id: '42', cid: '1', page: 1 });
    assert.equal(post.options.headers['X-MH'], '1');
    assert.equal(f.elements.s.textContent, 'стр. 2/2');
    f.elements.n.dispatch('click'); await flush();
    assert.equal(f.elements.v.children[0].textContent, 'Глава 2: <Вторая>');
    assert.equal(f.elements.v.children[0].focused, true);
    assert.equal(f.elements['reader-announcement'].textContent, 'Глава 2 из 2');
    assert.equal(f.elements.n.disabled, true);
    const chapterPost = requests.filter(request => request.url === '/api/progress').at(-1);
    assert.deepEqual(JSON.parse(chapterPost.options.body), { id: '42', cid: '2', page: 0 });
  } finally {
    for (const [name, value] of Object.entries(previous)) {
      if (value === undefined) delete globalThis[name]; else globalThis[name] = value;
    }
  }
});

test('reader reports a failed manga request without creating pages', async () => {
  const f = fixture();
  const previous = Object.fromEntries(['document', 'window', 'location', 'fetch'].map(name => [name, globalThis[name]]));
  try {
    globalThis.document = f.doc; globalThis.window = f.win; f.win.localStorage = f.storage;
    globalThis.location = { pathname: '/m/404' };
    globalThis.fetch = async () => ({ ok: false, json: async () => ({ error: 'not found' }) });
    const source = (await readFile(new URL('../ui/reader.js', import.meta.url), 'utf8'))
      .replace("'./preferences.js'", `'${dataUrl(prefSource)}'`).replace("'./reader-modes.js'", `'${modeUrl}'`).replace("'./reader-images.js'", `'${imageUrl}'`).replace("'./reader-progress.js'", `'${progressUrl}'`);
    await import(dataUrl(source + '\n// failed request')); await flush();
    assert.match(f.elements['reader-error'].textContent, /Не удалось открыть тайтл.*обновите страницу/);
    assert.equal(f.elements.v.querySelectorAll('img').length, 0);
  } finally {
    for (const [name, value] of Object.entries(previous)) {
      if (value === undefined) delete globalThis[name]; else globalThis[name] = value;
    }
  }
});
