import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
const source = await readFile(new URL('../ui/download-preflight.js', import.meta.url), 'utf8');
const { describePreflight, setupDownloadPreflight } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
const valid = { folder: 'C:\\saved', directory: { state: 'directory', free_bytes: '2097152' },
  tools: { source: 'app_folder', ffmpeg: 'found', ffprobe: 'missing' }, extension_online: true };

test('validates server result and clearly distinguishes observed facts from guarantees', () => {
  const lines = describePreflight(valid);
  assert.match(lines[0], /существует/); assert.match(lines[1], /2 МиБ/);
  assert.match(lines[2], /ffmpeg: файл найден; ffprobe: не найден/); assert.match(lines[3], /недавно/);
  const missing = describePreflight({ ...valid, directory: { state: 'missing', free_bytes: null }, extension_online: false });
  assert.match(missing[0], /не найдена/); assert.match(missing[1], /не определено/);
  assert.match(missing[3], /не обнаружено/);
  for (const bad of [null, { ...valid, folder: {} }, { ...valid, directory: { state: 'x', free_bytes: null } },
    { ...valid, directory: { state: 'directory', free_bytes: '-1' } }, { ...valid, tools: { ...valid.tools, ffmpeg: 'yes' } }]) {
    assert.throws(() => describePreflight(bad));
  }
});

class Element {
  constructor() { this.children = []; this.listeners = {}; this.value = ''; }
  setAttribute(k, v) { this[k] = v; }
  append(...nodes) { this.children.push(...nodes); }
  prepend(...nodes) { this.children.unshift(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  addEventListener(type, fn) { this.listeners[type] = fn; }
}
function fixture(fetcher) {
  const parent = new Element(), folder = new Element(); folder.value = valid.folder;
  const doc = { getElementById: () => folder, querySelector: () => parent, createElement: () => new Element() };
  let timer;
  const win = { setTimeout: fn => { timer = fn; return 1; }, clearTimeout() {} };
  setupDownloadPreflight({ doc, win, fetcher });
  const [heading, info, button, status, list] = parent.children[0].children;
  return { folder, heading, info, button, status, list, timeout: () => timer() };
}
const response = data => ({ ok: true, json: async () => data });

test('only explicit click sends protected request and renders text without changing settings', async () => {
  let calls = [];
  const f = fixture(async (url, opts) => { calls.push({ url, opts }); return response(valid); });
  assert.equal(calls.length, 0);
  assert.match(f.info.textContent, /Права на запись/);
  await f.button.listeners.click();
  assert.equal(calls.length, 1); assert.equal(calls[0].url, '/api/preflight');
  assert.equal(calls[0].opts.method, 'POST'); assert.equal(calls[0].opts.headers['X-MH'], '1');
  assert.equal(calls[0].opts.body, undefined); assert.equal(f.folder.value, valid.folder);
  assert.equal(f.list.children.length, 4); assert.match(f.status.textContent, /не гарантирует/);
  assert.equal(f.button.disabled, false);
});

test('folder edits or mismatch invalidate stale report and never overwrite input', async () => {
  let resolve;
  const f = fixture(() => new Promise(r => { resolve = r; }));
  const pending = f.button.listeners.click();
  assert.equal(f.button.disabled, true);
  f.folder.value = 'C:\\new'; f.folder.listeners.input();
  resolve(response(valid)); await pending;
  assert.equal(f.list.children.length, 0); assert.match(f.status.textContent, /Папка изменена/);
  assert.equal(f.folder.value, 'C:\\new'); assert.equal(f.button.disabled, false);
  const second = f.button.listeners.click(); resolve(response(valid)); await second;
  assert.equal(f.list.children.length, 0); assert.match(f.status.textContent, /Дождитесь сохранения/);
});

test('network errors and timeout report unknown outcome, allow later retry', async () => {
  let f = fixture(async () => { throw Error('offline'); });
  await f.button.listeners.click(); assert.match(f.status.textContent, /Проверка не выполнена/);
  assert.equal(f.button.disabled, false);
  f = fixture((_url, options) => new Promise((_resolve, reject) => options.signal.addEventListener('abort', () => reject(Error('aborted')))));
  const pending = f.button.listeners.click(); f.timeout(); await pending;
  assert.match(f.status.textContent, /сервер может продолжать/); assert.equal(f.button.disabled, false);
});
