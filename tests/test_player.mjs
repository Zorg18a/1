import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const dataUrl = source => `data:text/javascript;base64,${Buffer.from(source).toString('base64')}`;
const prefUrl = dataUrl(await readFile(new URL('../ui/preferences.js', import.meta.url), 'utf8'));
const subtitlesUrl = dataUrl(await readFile(new URL('../ui/player-subtitles.js', import.meta.url), 'utf8'));
const progressUrl = dataUrl(await readFile(new URL('../ui/player-progress.js', import.meta.url), 'utf8'));
const recentUrl = dataUrl(await readFile(new URL('../ui/recent.js', import.meta.url), 'utf8'));
const keysSource = (await readFile(new URL('../ui/player-keys.js', import.meta.url), 'utf8'))
  .replace("'./preferences.js'", `'${prefUrl}'`).replaceAll("'./player-subtitles.js'", `'${subtitlesUrl}'`);
const keysUrl = dataUrl(keysSource);
const { formatTime, cycleSubtitles, setupPlayerKeys } = await import(keysUrl);

class Element {
  constructor(tag = 'div') {
    this.tagName = tag.toUpperCase(); this.children = []; this.listeners = {}; this.dataset = {};
    this.textContent = ''; this.hidden = true; this.open = false; this.attrs = {};
    this.currentTime = 0; this.duration = 120; this.readyState = 1; this.playbackRate = 1;
    this.paused = true; this.muted = false; this.textTracks = []; this.plays = 0;
  }
  addEventListener(type, callback) { this.listeners[type] = callback; }
  dispatch(type) { return this.listeners[type]?.({ target: this }); }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
  setAttribute(key, value) { this.attrs[key] = value; }
  closest() { return null; }
  play() { this.paused = false; this.plays++; return Promise.resolve(); }
  pause() { this.paused = true; }
  showModal() { this.open = true; }
  close() { this.open = false; }
}
function fixture() {
  const ids = ['player-title', 'player-help', 'player-help-open', 'player-help-close', 'player-warning',
    'player-error', 'player-error-text', 'player-direct', 'player-container', 'player-announcement',
    'player-subtitle-control', 'player-subtitles', 'player-progress-status', 'player-restart'];
  const elements = Object.fromEntries(ids.map(id => [id, new Element()]));
  const doc = { documentElement: new Element('html'), getElementById: id => elements[id],
    createElement: tag => new Element(tag) };
  const win = { listeners: {}, addEventListener(type, callback) { this.listeners[type] = callback; } };
  const data = new Map();
  const storage = { getItem: key => data.get(key) ?? null, setItem: (key, value) => data.set(key, value) };
  return { doc, win, elements, data, storage };
}
function key(win, name, target = new Element(), extra = {}) {
  let prevented = false;
  win.listeners.keydown({ key: name, target, preventDefault() { prevented = true; }, ...extra });
  return prevented;
}
const flush = () => new Promise(resolve => setImmediate(resolve));

test('formats time and cycles through subtitle tracks', () => {
  assert.equal(formatTime(73), '1:13');
  assert.equal(formatTime(3661), '1:01:01');
  assert.equal(formatTime(NaN), '0:00');
  const media = { textTracks: [{ kind: 'subtitles', mode: 'disabled', label: 'Русский' }, { kind: 'captions', mode: 'disabled', label: 'English' }] };
  assert.equal(cycleSubtitles(media), 'Субтитры: Русский');
  assert.equal(cycleSubtitles(media), 'Субтитры: English');
  assert.equal(cycleSubtitles(media), 'Субтитры выключены');
  assert.deepEqual(media.textTracks.map(track => track.mode), ['disabled', 'disabled']);
  assert.equal(cycleSubtitles({ textTracks: [] }), 'Нет доступных субтитров');
});

test('hotkeys respect focus and preferences and handle player controls', async () => {
  const f = fixture(); const media = new Element('video'); let message = '', helped = false;
  setupPlayerKeys({ ...f, media, announce: value => { message = value; }, showHelp: () => { helped = true; } });
  assert.equal(key(f.win, 'k'), true); await flush();
  assert.equal(media.paused, false); assert.equal(message, 'Воспроизведение');
  key(f.win, 'k'); assert.equal(media.paused, true);
  key(f.win, 'l'); assert.equal(media.currentTime, 10);
  key(f.win, 'j'); key(f.win, 'j'); assert.equal(media.currentTime, 0);
  key(f.win, ']'); assert.equal(media.playbackRate, 1.25);
  media.textTracks = [{ kind: 'subtitles', mode: 'disabled', label: 'Русский' }];
  key(f.win, 'c'); assert.equal(media.textTracks[0].mode, 'showing');
  key(f.win, 'c'); assert.equal(media.textTracks[0].mode, 'disabled');
  key(f.win, 'm'); assert.equal(media.muted, true);
  key(f.win, '?'); assert.equal(helped, true);
  const field = new Element('input'); field.closest = () => field;
  assert.equal(key(f.win, 'm', field), false);
  const native = new Element('video'); native.closest = () => native;
  assert.equal(key(f.win, 'm', native), false);
  assert.equal(key(f.win, 'm', new Element(), { ctrlKey: true }), false);
  f.data.set('mediahub.display.v1', JSON.stringify({ hotkeys: false }));
  assert.equal(key(f.win, 'm'), false);
  assert.equal(media.muted, true);
});

test('player reports unavailable playback and metadata', async () => {
  const f = fixture(); const media = new Element('audio'); let message = '';
  media.play = () => { throw Error('blocked'); }; media.readyState = 0;
  setupPlayerKeys({ ...f, media, announce: value => { message = value; }, showHelp() {} });
  key(f.win, 'k'); await flush();
  assert.equal(message, 'Не удалось начать воспроизведение');
  key(f.win, 'l');
  assert.equal(message, 'Перемотка пока недоступна');
});

test('preview constructs native media and safe tracks without autoplay or server writes', async () => {
  const f = fixture(); const calls = [];
  const previous = Object.fromEntries(['document', 'window', 'location', 'fetch'].map(name => [name, globalThis[name]]));
  try {
    globalThis.document = f.doc; globalThis.window = f.win; f.win.localStorage = f.storage;
    globalThis.location = { pathname: '/p/1' };
    globalThis.fetch = async url => { calls.push(url); return { ok: true, json: async () => ({
      id: 1, title: '<Unsafe>', kind: 'video', src: '/f/1', cover: '', position_available: false,
      subs: [{ lang: 'en', label: 'English', url: '/sub/1/0.vtt?rev=' + 'a'.repeat(32) },
        { lang: 'en', label: 'unsafe', url: 'https://evil.invalid/track.vtt' }] }) }; };
    const source = (await readFile(new URL('../ui/player.js', import.meta.url), 'utf8'))
      .replace("'./preferences.js'", `'${prefUrl}'`).replace("'./player-keys.js'", `'${keysUrl}'`)
      .replace("'./player-subtitles.js'", `'${subtitlesUrl}'`).replace("'./player-progress.js'", `'${progressUrl}'`).replace("'./recent.js'", `'${recentUrl}'`);
    await import(dataUrl(source)); await flush();
    assert.deepEqual(calls, ['/api/player-preview/1']);
    assert.equal(f.elements['player-title'].textContent, '<Unsafe>');
    const media = f.elements['player-container'].children[0];
    assert.equal(media.tagName, 'VIDEO'); assert.equal(media.controls, true); assert.equal(media.preload, 'metadata');
    assert.equal(media.plays, 0); assert.equal(media.src, '/f/1');
    assert.equal(media.children.length, 1); assert.equal(media.children[0].kind, 'subtitles');
    media.children[0].dispatch('error');
    assert.match(f.elements['player-warning'].textContent, /Не удалось загрузить дорожку/);
    media.dispatch('error');
    assert.equal(f.elements['player-error'].hidden, false);
    assert.equal(f.elements['player-direct'].href, '/f/1');
    assert.equal(f.elements['player-direct'].hidden, false);
  } finally {
    for (const [name, value] of Object.entries(previous)) {
      if (value === undefined) delete globalThis[name]; else globalThis[name] = value;
    }
  }
});

test('preview reports missing material and does not create a media element', async () => {
  const f = fixture();
  const previous = Object.fromEntries(['document', 'window', 'location', 'fetch'].map(name => [name, globalThis[name]]));
  try {
    globalThis.document = f.doc; globalThis.window = f.win; f.win.localStorage = f.storage;
    globalThis.location = { pathname: '/p/7' };
    globalThis.fetch = async () => ({ ok: false, json: async () => ({ error: 'not found' }) });
    const source = (await readFile(new URL('../ui/player.js', import.meta.url), 'utf8'))
      .replace("'./preferences.js'", `'${prefUrl}'`).replace("'./player-keys.js'", `'${keysUrl}'`)
      .replace("'./player-subtitles.js'", `'${subtitlesUrl}'`).replace("'./player-progress.js'", `'${progressUrl}'`).replace("'./recent.js'", `'${recentUrl}'`);
    await import(dataUrl(source + '\n// missing')); await flush();
    assert.equal(f.elements['player-container'].children.length, 0);
    assert.equal(f.elements['player-error'].hidden, false);
    assert.equal(f.elements['player-direct'].hidden, true);
  } finally {
    for (const [name, value] of Object.entries(previous)) {
      if (value === undefined) delete globalThis[name]; else globalThis[name] = value;
    }
  }
});

test('audio preview renders decorative cover and warns about unavailable subtitles', async () => {
  const f = fixture();
  const previous = Object.fromEntries(['document', 'window', 'location', 'fetch'].map(name => [name, globalThis[name]]));
  try {
    globalThis.document = f.doc; globalThis.window = f.win; f.win.localStorage = f.storage;
    globalThis.location = { pathname: '/p/2' };
    globalThis.fetch = async () => ({ ok: true, json: async () => ({
      id: 2, title: 'Audio', kind: 'audio', src: '/f/2', cover: '/t/2', subs: [], subtitle_warning: true }) });
    const source = (await readFile(new URL('../ui/player.js', import.meta.url), 'utf8'))
      .replace("'./preferences.js'", `'${prefUrl}'`).replace("'./player-keys.js'", `'${keysUrl}'`)
      .replace("'./player-subtitles.js'", `'${subtitlesUrl}'`).replace("'./player-progress.js'", `'${progressUrl}'`).replace("'./recent.js'", `'${recentUrl}'`);
    await import(dataUrl(source + '\n// audio')); await flush();
    const [cover, media] = f.elements['player-container'].children;
    assert.equal(cover.tagName, 'IMG'); assert.equal(cover.alt, ''); assert.equal(cover.src, '/t/2');
    assert.equal(media.tagName, 'AUDIO'); assert.equal(media.controls, true);
    assert.match(f.elements['player-warning'].textContent, /субтитры/);
  } finally {
    for (const [name, value] of Object.entries(previous)) {
      if (value === undefined) delete globalThis[name]; else globalThis[name] = value;
    }
  }
});
