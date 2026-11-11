import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
const source = await readFile(new URL('../ui/extension-guide.js', import.meta.url), 'utf8');
const { connectionSummary, setupExtensionGuide } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
class Element {
  constructor() { this.children = []; this.listeners = {}; this.value = ''; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  setAttribute(name, value) { this[name] = value; }
  addEventListener(name, fn) { this.listeners[name] = fn; }
}
function fixture(fetcher) {
  const section = new Element(); const anchor = { closest: () => section };
  const doc = { getElementById: () => anchor, createElement: () => new Element() };
  let timeout;
  const win = { setTimeout: fn => { timeout = fn; return 1; }, clearTimeout() {} };
  setupExtensionGuide({ doc, win, fetcher });
  const [title, label, select, steps, note, button, status] = section.children[0].children[0].children;
  return { title, label, select, steps, note, button, status, timeout: () => timeout() };
}
const reply = data => ({ ok: true, json: async () => data });

test('browser-specific instructions avoid automatic requests, consent or tab transfer', () => {
  const calls = [];
  const f = fixture((...args) => calls.push(args));
  assert.equal(calls.length, 0); assert.equal(f.steps.children.length, 0);
  assert.equal(f.label.htmlFor, 'extension-browser');
  for (const [browser, path] of [['chrome', 'chrome://extensions'], ['edge', 'edge://extensions'],
    ['yandex', 'browser://extensions'], ['brave', 'brave://extensions'], ['firefox', 'about:debugging']]) {
    f.select.value = browser; f.select.listeners.change();
    assert.match(f.steps.children[0].textContent, new RegExp(path));
    assert.match(f.steps.children[1].textContent, /отправить выбранные адреса и названия/);
    assert.match(f.steps.children[2].textContent, /Отклонить/);
  }
  assert.match(f.steps.children[0].textContent, /перезапуска Firefox/);
  assert.match(f.note.textContent, /может храниться/); assert.match(f.note.textContent, /могут закрыться/);
  assert.equal(calls.length, 0);
});

test('manual status is aggregated, shows pending and does not interpret permission as live', async () => {
  const calls = [];
  const f = fixture(async (url, options) => { calls.push([url, options]); return reply({ paired: ['secret-origin'], pending: [{ name: '<script>' }] }); });
  await f.button.listeners.click();
  assert.equal(calls.length, 1); assert.equal(calls[0][0], '/api/ext'); assert.equal(calls[0][1].cache, 'no-store');
  assert.equal(calls[0][1].method, undefined); assert.equal(calls[0][1].body, undefined);
  assert.match(f.status.textContent, /разрешений — 1, ожидающих запросов — 1/);
  assert.match(f.status.textContent, /не статус выбранного браузера/); assert.match(f.status.textContent, /не подтверждает/);
  assert.doesNotMatch(f.status.textContent, /secret-origin|script/);
  assert.match(connectionSummary({ paired: [], pending: [] }), /отклонено или запрос истёк/);
  assert.throws(() => connectionSummary({ paired: [], pending: 'bad' }));
});

test('network failure, malformed reply and timeout allow retry', async () => {
  let n = 0;
  const f = fixture(async () => { if (!n++) throw new Error('offline'); return reply({ paired: [], pending: [] }); });
  await f.button.listeners.click(); assert.match(f.status.textContent, /неизвестно/); assert.equal(f.button.disabled, false);
  await f.button.listeners.click(); assert.match(f.status.textContent, /разрешений — 0/);
  const bad = fixture(async () => reply({ pending: [] })); await bad.button.listeners.click();
  assert.match(bad.status.textContent, /Некорректный ответ/);
  const t = fixture((_url, options) => new Promise((_resolve, reject) => options.signal.addEventListener('abort', () => reject(Error('abort')))));
  const pending = t.button.listeners.click(); await t.button.listeners.click(); t.timeout(); await pending;
  assert.match(t.status.textContent, /время ожидания истекло/); assert.equal(t.button.disabled, false);
});
