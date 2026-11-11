import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
const source = await readFile(new URL('../ui/backup.js', import.meta.url), 'utf8');
const { downloadBackup, inspectBackup, setupBackup } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);

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
const digest = createHash('sha256').update(Buffer.from(await image.arrayBuffer())).digest('hex');
function response(blob = image, type = 'application/vnd.sqlite3', length = String(blob.size), sha = digest) {
  return { ok: true, headers: { get: key => ({ 'content-type': type, 'content-length': length, 'x-backup-sha256': sha })[key] }, blob: async () => blob };
}

test('download is initiated with checked SQLite content, then object URL is released', async () => {
  const f = fixture(); let request;
  assert.equal(await downloadBackup({ ...f, fetcher: async (...args) => { request = args; return response(); } }), digest);
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
    response(new Blob([new Uint8Array(116)])), response(image, 'application/vnd.sqlite3', String(image.size), 'bad'),
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
  assert.match(status.textContent, new RegExp(digest));
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

test('inspection validates the selected file and checks the server response', async () => {
  let call;
  const inspect = async (...args) => { call = args; return { ok: true, json: async () => ({ ok: 1, items: 4, progress: 2, sha256: digest }) }; };
  assert.deepEqual(await inspectBackup(image, inspect), { ok: 1, items: 4, progress: 2, sha256: digest });
  assert.equal(call[0], '/api/backup/inspect'); assert.equal(call[1].body, image);
  assert.equal(call[1].headers['Content-Type'], 'application/octet-stream');
  assert.equal(call[1].headers['X-MH'], '1');
  await assert.rejects(inspectBackup(null, inspect));
  await assert.rejects(inspectBackup(new Blob(['tiny']), inspect));
  for (const answer of [
    { ok: false, json: async () => ({ error: 'Неверная копия' }) },
    { ok: true, json: async () => ({ ok: 1, items: -1, progress: 2, sha256: digest }) },
    { ok: true, json: async () => ({ ok: 1, items: 4, progress: 2 }) },
    { ok: true, json: async () => ({ ok: 1, items: 4, progress: 2, sha256: 'bad' }) },
    { ok: true, json: async () => { throw Error('bad'); } },
  ]) await assert.rejects(inspectBackup(image, async () => answer));
  await assert.rejects(inspectBackup(image, async () => { throw Error('offline'); }));
});

test('inspection UI prevents duplicate uploads and never claims restoration', async () => {
  const f = fixture(); let resolve, requests = 0;
  setupBackup({ ...f, fetcher: () => { requests++; return new Promise(r => { resolve = r; }); } });
  const [, , , , label, file, verify, report] = f.parent.children[0].children;
  assert.equal(label.htmlFor, 'backup-file'); file.files = [image];
  const running = verify.click(); verify.click();
  assert.equal(requests, 1); assert.equal(file.disabled, true); assert.equal(verify.disabled, true);
  resolve({ ok: true, json: async () => ({ ok: 1, items: 2, progress: 3, sha256: digest }) }); await running;
  assert.equal(file.disabled, false); assert.equal(verify.disabled, false);
  assert.match(report.textContent, /материалов 2, позиций манги 3/);
  assert.match(report.textContent, /восстановление не выполнялось/);
  assert.match(report.textContent, new RegExp(digest));
  file.listeners.change(); assert.equal(report.textContent, '');
});
