import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
const source = await readFile(new URL('../ui/backup.js', import.meta.url), 'utf8');
const { downloadBackup, setupBackup } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);

class Element {
  constructor() { this.children = []; this.listeners = {}; this.textContent = ''; this.disabled = false; }
  append(...children) { this.children.push(...children); }
  prepend(child) { this.children.unshift(child); }
  addEventListener(type, fn) { this.listeners[type] = fn; }
  setAttribute(key, value) { this[key] = value; }
  click() { this.clicked = true; return this.listeners.click?.(); }
  remove() { this.removed = true; }
}
function fixture() {
  const parent = new Element(), body = new Element(), revoked = [];
  const doc = { body, createElement: () => new Element(), querySelector: () => parent };
  const win = { URL: { createObjectURL: () => 'blob:backup', revokeObjectURL: url => revoked.push(url) },
    setTimeout: callback => { win.cleanup = callback; } };
  return { parent, body, doc, win, revoked };
}
const image = new Blob([new TextEncoder().encode('SQLite format 3\0'), new Uint8Array(100)]);
function response(blob = image, type = 'application/vnd.sqlite3', length = String(blob.size)) {
  return { ok: true, headers: { get: key => ({ 'content-type': type, 'content-length': length })[key] }, blob: async () => blob };
}

test('download is initiated with checked SQLite content, then object URL is released', async () => {
  const f = fixture(); let request;
  await downloadBackup({ ...f, fetcher: async (...args) => { request = args; return response(); } });
  assert.equal(request[0], '/api/backup'); assert.equal(request[1].method, 'POST');
  assert.equal(request[1].headers['X-MH'], '1');
  const link = f.body.children[0]; assert.equal(link.clicked, true); assert.equal(link.removed, true);
  assert.match(link.download, /^mediahub-library-.*\.db$/);
  assert.deepEqual(f.revoked, []); f.win.cleanup(); assert.deepEqual(f.revoked, ['blob:backup']);
});

test('HTTP errors, bad type, wrong size and corrupt header do not trigger a download', async () => {
  const f = fixture();
  for (const result of [
    { ok: false, json: async () => ({ error: 'База занята' }) },
    response(image, 'text/html'), response(image, 'application/vnd.sqlite3', '2'),
    response(image, 'application/vnd.sqlite3', '120'),
    response(new Blob([new Uint8Array(116)])),
  ]) await assert.rejects(downloadBackup({ ...f, fetcher: async () => result }));
  assert.equal(f.body.children.length, 0);
});

test('UI prevents duplicate requests and never claims a file was saved', async () => {
  const f = fixture(); let resolve, requests = 0;
  setupBackup({ ...f, fetcher: () => { requests++; return new Promise(r => { resolve = r; }); } });
  const [heading, info, button, status] = f.parent.children[0].children;
  assert.match(heading.textContent, /Резервная копия/);
  assert.match(info.textContent, /Медиафайлы/); assert.equal(status.role, 'status');
  const running = button.click(); button.click();
  assert.equal(requests, 1); assert.equal(button.disabled, true);
  resolve(response()); await running;
  assert.equal(button.disabled, false); assert.match(status.textContent, /передан браузеру.*Проверьте загрузки/);
});

test('UI reports failed or blocked browser downloads and allows retry', async () => {
  const f = fixture();
  setupBackup({ ...f, fetcher: async () => ({ ok: false, json: async () => ({ error: 'База занята' }) }) });
  const button = f.parent.children[0].children[2], status = f.parent.children[0].children[3];
  await button.click();
  assert.equal(button.disabled, false); assert.match(status.textContent, /База занята/);
  f.win.URL.createObjectURL = () => { throw Error('blocked'); };
  await assert.rejects(downloadBackup({ ...f, fetcher: async () => response() }));
});
