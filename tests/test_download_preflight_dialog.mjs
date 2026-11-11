import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
const dataUrl = source => `data:text/javascript;base64,${Buffer.from(source).toString('base64')}`;
const shared = dataUrl(await readFile(new URL('../ui/download-preflight.js', import.meta.url), 'utf8'));
const source = (await readFile(new URL('../ui/download-preflight-dialog.js', import.meta.url), 'utf8'))
  .replace("'./download-preflight.js'", `'${shared}'`);
const { setupDialogPreflight } = await import(dataUrl(source));
const result = { folder: 'C:\\<img onerror=alert(1)>', directory: { state: 'directory', free_bytes: '1048576' },
  tools: { source: 'path', ffmpeg: 'found', ffprobe: 'missing' }, extension_online: false };
const response = data => ({ ok: true, json: async () => data });

class Element {
  constructor() { this.children = []; this.listeners = {}; this.style = {}; this.open = false; }
  setAttribute(k, v) { this[k] = v; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  before(node) { this.inserted = node; }
  addEventListener(type, fn) { this.listeners[type] = fn; }
}
function fixture(fetcher) {
  const dialog = new Element(), preview = new Element(), folder = new Element(); dialog.open = true;
  const nodes = { addDlg: dialog, pv: preview, s_folder: folder };
  const doc = { getElementById: id => nodes[id], createElement: () => new Element() };
  let timer;
  const win = { setTimeout: fn => { timer = fn; return 1; }, clearTimeout() {} };
  setupDialogPreflight({ doc, win, fetcher });
  const details = preview.inserted, [summary, content] = details.children;
  const [info, button, status, list] = content.children;
  return { dialog, folder, details, summary, info, button, status, list, timeout: () => timer() };
}

test('explicit optional check displays saved path as text, without submitting download', async () => {
  const calls = [];
  const f = fixture(async (url, options) => { calls.push({ url, options }); return response(result); });
  assert.match(f.summary.textContent, /необязательно/); assert.equal(f.details.open, false);
  assert.equal(calls.length, 0); assert.match(f.info.textContent, /не запускает загрузку/);
  await f.button.listeners.click();
  assert.equal(calls.length, 1); assert.equal(calls[0].url, '/api/preflight');
  assert.equal(calls[0].options.method, 'POST'); assert.equal(calls[0].options.body, undefined);
  assert.equal(calls[0].options.headers['X-MH'], '1');
  assert.equal(f.list.children.length, 5);
  assert.equal(f.list.children[0].textContent, `Сохранённая папка на момент проверки: ${result.folder}`);
  assert.equal(f.list.children[0].children.length, 0);
  assert.match(f.status.textContent, /не гарантирует успешную загрузку/);
  assert.equal(f.button.disabled, false);
});

test('closing clears results and prevents a delayed response from appearing after reopen', async () => {
  let resolve, captured;
  const f = fixture((_url, options) => { captured = options.signal; return new Promise(r => { resolve = r; }); });
  f.details.open = true;
  const pending = f.button.listeners.click(); assert.equal(f.button.disabled, true);
  f.dialog.open = false; f.dialog.listeners.close();
  assert.equal(captured.aborted, true); assert.equal(f.details.open, false);
  f.dialog.open = true; resolve(response(result)); await pending;
  assert.equal(f.list.children.length, 0); assert.equal(f.status.textContent, '');
  assert.equal(f.button.disabled, false);
});

test('folder changes invalidate pending results; server errors and timeout permit retry', async () => {
  let resolve;
  let f = fixture(() => new Promise(r => { resolve = r; }));
  const pending = f.button.listeners.click(); f.folder.listeners.input(); resolve(response(result)); await pending;
  assert.equal(f.list.children.length, 0); assert.match(f.status.textContent, /Папка изменена/);
  f = fixture(async () => ({ ok: false, json: async () => ({ error: 'Проверка уже выполняется.' }) }));
  await f.button.listeners.click(); assert.match(f.status.textContent, /уже выполняется/); assert.equal(f.button.disabled, false);
  f = fixture((_url, options) => new Promise((_r, reject) => options.signal.addEventListener('abort', () => reject(Error('aborted')))));
  const timeout = f.button.listeners.click(); f.timeout(); await timeout;
  assert.match(f.status.textContent, /сервер может продолжать/); assert.equal(f.button.disabled, false);
});
