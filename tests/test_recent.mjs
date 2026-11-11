import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
const source = await readFile(new URL('../ui/recent.js', import.meta.url), 'utf8');
const { readRecent, recordRecent, expectedRecentIdentity, setupRecent } =
  await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
const key = 'mediahub.recent.v1', a = 'a'.repeat(64), b = 'b'.repeat(64);
const flush = () => new Promise(resolve => setImmediate(resolve));
function fixture() {
  let value = null;
  const storage = { getItem: () => value, setItem: (_k, v) => { value = v; }, removeItem: () => { value = null; } };
  return { storage, set: v => { value = v; }, get: () => value };
}
const item = (id = '1', identity = a) => ({ id, kind: 'video', identity, live_identity: b, title: '<img onerror=alert(1)>' });
const response = data => ({ ok: true, json: async () => data });

test('validated, bounded local entries contain no title or URL; identity must match opened page', async () => {
  const f = fixture();
  assert.equal(await recordRecent({ storage: f.storage, fetcher: async () => response(item()), id: '1', kind: 'video', liveIdentity: a }), false);
  for (let i = 1; i <= 15; i++) {
    assert.equal(await recordRecent({ storage: f.storage, fetcher: async () => response(item(String(i))), id: String(i), kind: 'video', liveIdentity: b }), true);
  }
  assert.equal(readRecent(f.storage).length, 12);
  assert.equal(readRecent(f.storage)[0].id, '15');
  assert.doesNotMatch(f.get(), /title|url|img/);
  f.set(JSON.stringify([{ id: '01', kind: 'video', identity: a }, { id: '9223372036854775808', kind: 'video', identity: a },
    { id: '2', kind: 'video', identity: a, title: 'bad' }, { id: '2', kind: 'video', identity: a }]));
  assert.deepEqual(readRecent(f.storage), [{ id: '2', kind: 'video', identity: a }]);
  f.set('x'.repeat(10001)); assert.deepEqual(readRecent(f.storage), []);
  assert.deepEqual(readRecent(null), []);
  assert.equal(await recordRecent({ storage: null, fetcher: async () => response(item()), id: '1', kind: 'video', liveIdentity: b }), false);
  assert.equal(expectedRecentIdentity(''), null);
  assert.equal(expectedRecentIdentity('?recent=' + a), a);
  assert.equal(expectedRecentIdentity('?recent=bad'), '');
  assert.equal(expectedRecentIdentity(`?recent=${a}&recent=${a}`), '');
});

class Element {
  constructor() { this.children = []; this.handlers = {}; this.style = {}; }
  setAttribute(k, v) { this[k] = v; }
  append(...nodes) { this.children.push(...nodes); }
  before(node) { this.inserted = node; }
  replaceChildren(...nodes) { this.children = nodes; }
  addEventListener(type, fn) { this.handlers[type] = fn; }
}

test('fresh server title as text, click revalidation, stale response and clear', async () => {
  const f = fixture(); f.set(JSON.stringify([{ id: '1', kind: 'video', identity: a }]));
  const lib = new Element(), handlers = {}, destinations = [];
  const doc = { createElement: () => new Element(), getElementById: () => lib };
  const win = { addEventListener: (type, fn) => { handlers[type] = fn; }, location: { assign: path => destinations.push(path) } };
  let current = item();
  const fetcher = async () => response(current);
  setupRecent({ doc, win, storage: f.storage, fetcher });
  await flush();
  const [, , status, list, clear] = lib.inserted.children;
  assert.equal(list.children[0].textContent, 'Плеер: <img onerror=alert(1)>');
  current = item('1', b);
  await list.children[0].handlers.click();
  assert.equal(destinations.length, 0); assert.match(status.textContent, /изменился/);
  current = item();
  await list.children[0].handlers.click();
  assert.deepEqual(destinations, ['/p/1?recent=' + b]);
  clear.handlers.click(); assert.equal(f.get(), null); assert.equal(list.children.length, 0);
  assert.match(status.textContent, /очищена/);
  handlers.storage({ key }); await flush(); assert.equal(list.children.length, 0);
});

test('clearing prevents pending refresh and click from restoring stale entries', async () => {
  const f = fixture(); f.set(JSON.stringify([{ id: '1', kind: 'video', identity: a }]));
  const lib = new Element(); let resolve;
  const doc = { createElement: () => new Element(), getElementById: () => lib };
  const win = { addEventListener() {}, location: { assign() { assert.fail('stale navigation'); } } };
  setupRecent({ doc, win, storage: f.storage, fetcher: () => new Promise(r => { resolve = r; }) });
  const [, , status, list, clear] = lib.inserted.children;
  clear.handlers.click(); resolve(response(item())); await flush();
  assert.equal(list.children.length, 0); assert.match(status.textContent, /очищена/);
});
