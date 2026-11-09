import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const source = await readFile(new URL('../ui/game-update-preview.js', import.meta.url), 'utf8');
const { setupUpdatePreview, inspectCandidate, setupSavePreview } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);

test('preview requests only an id, reports failures and renders names as text', async () => {
  const keys = ['window', 'document', 'fetch'];
  const old = Object.fromEntries(keys.map(key => [key, globalThis[key]]));
  const listeners = {};
  const status = { textContent: '' }, results = { children: [], replaceChildren() { this.children = []; }, append(x) { this.children.push(x); } };
  const button = { disabled: false, addEventListener(_type, fn) { this.click = fn; } };
  const saveButton = { addEventListener() {} };
  const section = { isConnected: true, querySelector(s) { return s === '.save-preview-button' ? saveButton : s === 'button' ? button : s === '[role="status"]' ? status : results; } };
  let inserted = false, request, fail = true, tick, cleared = false;
  const panel = { querySelector(s) { return s === '.update-preview' ? (inserted ? section : null) : {}; },
    insertBefore() { inserted = true; } };
  try {
    globalThis.window = { addEventListener(type, fn) { listeners[type] = fn; },
      setInterval(fn, ms) { assert.equal(ms, 15000); tick = fn; return 1; }, clearInterval() { cleared = true; } };
    globalThis.document = { querySelector: s => s === '#gpanel' ? { getAttribute: () => 'false' } : s === '#v-games' ? null : panel, createElement(tag) {
      return tag === 'section' ? section : { tag, children: [], append(x) { this.children.push(x); }, textContent: '' };
    } };
    globalThis.fetch = async (url, opts) => {
      request = { url, opts };
      return fail ? { ok: false, json: async () => ({ error: 'Нет доступа' }) } : {
        ok: true, json: async () => ({ folder: 'C:/MediaHub/Incoming_Downloads', installed_version: '1', latest_version: '2',
          candidates: [{ name: '<img>.zip', size: 1024, version: '2' }], truncated: false }) };
    };
    setupUpdatePreview();
    listeners['mediahub:game-panel']({ detail: { id: 7, g: { downloaded: false } } });
    assert.equal(inserted, false);
    listeners['mediahub:game-panel']({ detail: { id: 7, g: { downloaded: true } } });
    assert.equal(inserted, true);
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(status.textContent, 'Нет доступа');
    assert.equal(button.disabled, false);
    fail = false;
    tick();
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(request.url, '/api/game/incoming');
    assert.equal(request.opts.headers['X-MH'], '1');
    assert.deepEqual(JSON.parse(request.opts.body), { id: 7 });
    assert.equal(results.children[1].children[0].textContent, '<img>.zip — 1.00 КиБ, версия в имени: 2');
    assert.match(status.textContent, /1/);
    assert.match(results.children[2].textContent, /не распакованы/);
    const previous = results.children[0];
    tick(); await new Promise(resolve => setImmediate(resolve));
    assert.equal(results.children[0], previous);
    await button.click();
    section.isConnected = false; tick();
    assert.equal(cleared, true);
  } finally {
    for (const key of keys) { if (old[key] === undefined) delete globalThis[key]; else globalThis[key] = old[key]; }
  }
});

test('explicit ZIP inspection reports metadata limits and stale archive errors', async () => {
  const original = globalThis.fetch;
  const button = { disabled: false }, status = { textContent: '' };
  const candidate = { name: 'Game.zip', identity: 'abc' };
  let failed = false, request;
  try {
    globalThis.fetch = async (url, options) => {
      request = { url, options };
      assert.equal(button.disabled, true);
      return failed ? { ok: false, json: async () => ({ error: 'Архив изменился' }) } :
        { ok: true, json: async () => ({ inspection: { files: 3, uncompressed_bytes: 2048 } }) };
    };
    await inspectCandidate(7, candidate, button, status);
    assert.equal(request.url, '/api/game/zip-inspect');
    assert.deepEqual(JSON.parse(request.options.body), { id: 7, name: 'Game.zip', identity: 'abc' });
    assert.equal(request.options.headers['X-MH'], '1');
    assert.match(status.textContent, /файлов 3/);
    assert.match(status.textContent, /CRC не проверены/);
    assert.equal(button.disabled, false);
    globalThis.fetch = async (_url, options) => {
      assert.equal(JSON.parse(options.body).verify_data, true);
      return { ok: true, json: async () => ({ inspection: { verified_files: 1, verified_bytes: 42 } }) };
    };
    await inspectCandidate(7, candidate, button, status, true);
    assert.match(status.textContent, /Данные и CRC проверены/);
    assert.match(status.textContent, /не подтверждает безопасность/);
    globalThis.fetch = async () => ({ ok: false, json: async () => ({ error: 'Архив изменился' }) });
    failed = true;
    await inspectCandidate(7, candidate, button, status);
    assert.equal(status.textContent, 'Архив изменился');
    assert.equal(button.disabled, false);
  } finally { globalThis.fetch = original; }
});

test('ZIP data check is only started by its labeled button', async () => {
  const old = Object.fromEntries(['window', 'document', 'fetch'].map(k => [k, globalThis[k]]));
  const handlers = {}, requests = [];
  class Element {
    constructor() { this.children = []; this.attrs = {}; this.disabled = false; this.isConnected = true; }
    setAttribute(k, v) { this.attrs[k] = v; }
    getAttribute(k) { return this.attrs[k] ?? null; }
    addEventListener(type, fn) { this[type] = fn; }
    append(...nodes) { this.children.push(...nodes); }
    replaceChildren() { this.children = []; }
    contains(el) { return this.children.some(c => c === el || c.contains(el)); }
    querySelectorAll() { return this.children.flatMap(c => [c, ...c.querySelectorAll()]).filter(c => c.attrs['data-zip-name']); }
    focus() { globalThis.document.activeElement = this; }
  }
  const button = new Element(), status = new Element(), results = new Element(), section = new Element();
  const saveButton = new Element();
  section.querySelector = s => s === '.save-preview-button' ? saveButton : s === 'button' ? button : s === '[role="status"]' ? status : results;
  const panel = { querySelector: s => s === '.update-preview' ? null : {}, insertBefore() {} };
  try {
    globalThis.window = { addEventListener: (t, f) => { handlers[t] = f; }, setInterval: () => 1 };
    globalThis.document = { activeElement: null, querySelector: () => panel, createElement: t => t === 'section' ? section : new Element() };
    globalThis.fetch = async (url, options) => {
      requests.push({ url, body: JSON.parse(options.body) });
      return { ok: true, json: async () => url.endsWith('incoming') ?
        { folder: 'x', candidates: [{ name: 'Game.zip', identity: 'a', size: 1 }] } :
        JSON.parse(options.body).compare_saves ? { inspection: { save_comparison: { game_folder: 'x', incomplete: false, candidates: [] } } } :
        { inspection: { verified_files: 1, verified_bytes: 1 } } };
    };
    setupUpdatePreview();
    handlers['mediahub:game-panel']({ detail: { id: 7, g: { downloaded: true } } });
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(requests.length, 1);
    const buttons = results.querySelectorAll();
    assert.equal(buttons.length, 3);
    assert.match(buttons[2].getAttribute('aria-label'), /сохранений с ZIP.*Game.zip/);
    assert.match(buttons[1].getAttribute('aria-label'), /CRC.*Game.zip/);
    await buttons[1].click();
    assert.equal(requests[1].body.verify_data, true);
    assert.match(results.children[1].children[0].children[3].textContent, /CRC проверены/);
    await buttons[2].click();
    assert.equal(requests[2].body.compare_saves, true);
    assert.match(results.children[1].children[0].children[3].textContent, /не план установки/);
  } finally {
    for (const k of Object.keys(old)) { if (old[k] === undefined) delete globalThis[k]; else globalThis[k] = old[k]; }
  }
});

test('save discovery is explicit, renders paths as text and warns on incomplete search', async () => {
  const oldFetch = globalThis.fetch, oldDocument = globalThis.document;
  const button = { disabled: false, addEventListener(_event, fn) { this.click = fn; } };
  const status = { textContent: '' };
  const results = { children: [], replaceChildren() { this.children = []; }, append(x) { this.children.push(x); } };
  const section = { querySelector: s => s === '.save-preview-button' ? button : s === '.save-preview-status' ? status : results };
  const requests = [];
  try {
    globalThis.document = { createElement: () => ({ children: [], append(child) { this.children.push(child); }, textContent: '' }) };
    globalThis.fetch = async (url, opts) => {
      requests.push({ url, body: JSON.parse(opts.body) });
      return { ok: true, json: async () => ({ save_preview: { game_folder: 'C:/Game', incomplete: true,
        candidates: [{ path: '<img>.sav', kind: 'file' }] } }) };
    };
    setupSavePreview(7, section);
    assert.equal(requests.length, 0);
    await button.click();
    assert.deepEqual(requests[0], { url: '/api/game/incoming', body: { id: 7, mode: 'saves' } });
    assert.equal(results.children[0].children[0].textContent, '<img>.sav (файл)');
    assert.match(status.textContent, /Поиск неполный/);
    assert.match(status.textContent, /не резервная копия/);
    assert.equal(button.disabled, false);
    globalThis.fetch = async () => ({ ok: false, json: async () => ({ error: 'Нет доступа' }) });
    await button.click();
    assert.equal(status.textContent, 'Нет доступа');
    assert.equal(results.children.length, 0);
  } finally { globalThis.fetch = oldFetch; globalThis.document = oldDocument; }
});
