import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const source = await readFile(new URL('../ui/game-update-preview.js', import.meta.url), 'utf8');
const { setupUpdatePreview, inspectCandidate } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);

test('preview requests only an id, reports failures and renders names as text', async () => {
  const keys = ['window', 'document', 'fetch'];
  const old = Object.fromEntries(keys.map(key => [key, globalThis[key]]));
  const listeners = {};
  const status = { textContent: '' }, results = { children: [], replaceChildren() { this.children = []; }, append(x) { this.children.push(x); } };
  const button = { disabled: false, addEventListener(_type, fn) { this.click = fn; } };
  const section = { isConnected: true, querySelector(s) { return s === 'button' ? button : s === '[role="status"]' ? status : results; } };
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
    failed = true;
    await inspectCandidate(7, candidate, button, status);
    assert.equal(status.textContent, 'Архив изменился');
    assert.equal(button.disabled, false);
  } finally { globalThis.fetch = original; }
});
