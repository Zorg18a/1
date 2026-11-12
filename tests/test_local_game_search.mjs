import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
const source = await readFile(new URL('../ui/local-game-search.js', import.meta.url), 'utf8');
const { setupLocalGameSearch } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);

class Element {
  children = []; handlers = {}; textContent = ''; disabled = false; attrs = {};
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
  setAttribute(key, value) { this.attrs[key] = value; }
  addEventListener(type, fn) { this.handlers[type] = fn; }
  click() { return this.handlers.click?.(); }
}
function setup(fetcher, confirm = () => true) {
  const panel = new Element(); panel.querySelector = () => null;
  panel.insertBefore = section => { panel.section = section; };
  const doc = { querySelector: () => panel, createElement: () => new Element() };
  const win = { addEventListener: (type, fn) => { win.open = fn; }, confirm, loadGames: async () => { win.reloaded = true; } };
  setupLocalGameSearch({ win, doc, fetcher });
  win.open({ detail: { id: 1, title: 'Hidden Badge', g: { downloaded: false } } });
  const [, , button, status, results, extra] = panel.section.children;
  const input = extra.children[0].children[0], extraButton = extra.children[2];
  return { button, status, results, win, input, extraButton };
}
const candidate = { path: 'G:\\PG\\new7\\HiddenBadge_20260828c', kind: 'folder', reason: 'дата', token: 'secret',
  association: { state: 'none', cards: [], extra: 0 } };
const result = { root: 'G:\\PG', scanned: 12, incomplete: true, candidates: [candidate] };
const ok = value => ({ ok: true, json: async () => value });

test('search reports incomplete, confirmation is explicit and text is not markup', async () => {
  const requests = []; let allow = false;
  const f = setup(async (url, opts) => { requests.push(JSON.parse(opts.body)); return ok(result); }, () => allow);
  await f.button.click();
  assert.match(f.status.textContent, /неполный/);
  const item = f.results.children[0].children[0];
  assert.match(item.children[0].textContent, /HiddenBadge/);
  const choose = item.children[2]; await choose.click();
  assert.equal(requests.length, 1);
  allow = true;
  // Switch the response for the link request without invoking a real server.
  assert.equal(choose.attrs['aria-label'], `Связать с карточкой: ${candidate.path}`);
});

test('link posts a token only after consent and refreshes the list', async () => {
  const calls = [];
  const f = setup(async (url, opts) => {
    const body = JSON.parse(opts.body); calls.push(body);
    return ok(body.mode === 'local_search' ? result : { ok: 1, path: candidate.path });
  });
  await f.button.click(); await f.results.children[0].children[0].children[2].click();
  assert.deepEqual(calls, [{ id: 1, mode: 'local_search' }, { id: 1, mode: 'local_link', token: 'secret' }]);
  assert.equal(f.win.reloaded, true);
});

test('linked cards are shown as text and opening one never links the path', async () => {
  const calls = [];
  const linked = { ...candidate, association: { state: 'other', cards: [{ id: 2, title: '<img onerror=bad>' }], extra: 1 } };
  const f = setup(async (url, opts) => { calls.push(JSON.parse(opts.body)); return ok({ ...result, candidates: [linked] }); });
  f.win.openPanel = id => { f.win.opened = id; };
  await f.button.click();
  const item = f.results.children[0].children[0];
  assert.match(item.children[1].textContent, /другой карточкой/);
  assert.match(item.children[2].textContent, /<img onerror=bad>/);
  assert.match(item.children[4].textContent, /Других связанных карточек: 1/);
  item.children[3].click(); assert.equal(f.win.opened, 2);
  assert.equal(calls.length, 1);
  assert.equal(item.children.some(c => c.textContent === 'Связать с этой карточкой'), false);
});

test('unknown association never offers binding even with a token', async () => {
  const f = setup(async () => ok({ ...result, candidates: [{ ...candidate, association: { state: 'unknown', cards: [], extra: 0 } }] }));
  await f.button.click(); const item = f.results.children[0].children[0];
  assert.match(item.children[1].textContent, /Не удалось проверить/);
  assert.equal(item.children.length, 2);
});

test('extra root is explicit, read-only and clears results when edited', async () => {
  const calls = [];
  const f = setup(async (url, opts) => { calls.push(JSON.parse(opts.body)); return ok(result); });
  f.input.value = '';
  await f.extraButton.click(); assert.equal(calls.length, 0); assert.match(f.status.textContent, /Укажите/);
  f.input.value = 'D:\\\\Games';
  await f.extraButton.click();
  assert.deepEqual(calls, [{ id: 1, mode: 'local_search_other', root: 'D:\\\\Games' }]);
  assert.match(f.status.textContent, /только просмотр/);
  assert.equal(f.results.children[0].children[0].children.length, 2); // No link even if a response contains a token.
  f.input.handlers.input(); assert.equal(f.results.children.length, 0);
});

test('stale association and malformed result show error and permit a new search', async () => {
  let calls = 0;
  const f = setup(async (url, opts) => {
    calls++;
    if (JSON.parse(opts.body).mode === 'local_search') return ok(result);
    return { ok: false, json: async () => ({ error: 'Карточка изменилась' }) };
  });
  await f.button.click(); await f.results.children[0].children[0].children[2].click();
  assert.match(f.status.textContent, /Карточка изменилась.*поиск заново/);
  assert.equal(f.button.disabled, false); assert.equal(f.results.children.length, 0);
  await f.button.click(); assert.equal(calls, 3);
  const invalid = setup(async () => ok({ ...result, candidates: 'bad' }));
  await invalid.button.click(); assert.match(invalid.status.textContent, /Некорректный/);
});
