import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';

const source = await readFile(new URL('../ui/library-search.js', import.meta.url), 'utf8');
const { setupLibrarySearch } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
const html = await readFile(new URL('../ui/index.html', import.meta.url), 'utf8');
const libCode = html.match(/^async function lib\(\).*$/m)?.[0];
const inputCode = html.match(/^\['gb','so'\].*$/m)?.[0];
assert.ok(libCode && inputCode);

class Element {
  constructor() { this.children = []; this.handlers = {}; this.value = ''; }
  setAttribute(key, value) { this[key] = value; }
  append(...nodes) { this.children.push(...nodes); }
  addEventListener(type, fn) { this.handlers[type] = fn; }
  focus() { this.focused = true; }
}

test('counts only current results, reports failures, and resets search and type only', () => {
  const query = new Element(), tools = new Element(), calls = [];
  const doc = { createElement: () => new Element(), getElementById: () => query, querySelector: () => tools };
  const win = { setK: k => calls.push(['type', k]), searchNow: () => calls.push(['search']) };
  setupLibrarySearch({ doc, win });
  const [reset, status] = tools.children[0].children;
  assert.equal(query['aria-label'], 'Поиск в библиотеке по названию, автору и теме');
  assert.equal(status['aria-live'], 'polite');
  assert.match(status.textContent, /Обновляем/);
  assert.deepEqual(calls, [['search']]);
  win.MediaHubLibraryDrawn(11, ''); assert.match(status.textContent, /Обновляем/);
  win.MediaHubLibraryLoaded(); win.MediaHubLibraryDrawn(3, '');
  assert.equal(status.textContent, 'Показано материалов: 3');
  query.value = 'новый запрос'; win.MediaHubLibraryDrawn(9, '');
  assert.equal(status.textContent, 'Показано материалов: 3');
  win.MediaHubLibraryPending(); win.MediaHubLibraryDrawn(9, ''); assert.match(status.textContent, /Обновляем/);
  win.MediaHubLibraryError(); win.MediaHubLibraryDrawn(9, 'новый запрос');
  assert.match(status.textContent, /прежние результаты/);
  reset.handlers.click();
  assert.equal(query.value, ''); assert.equal(query.focused, true);
  assert.deepEqual(calls.slice(1), [['type', ''], ['search']]);
  assert.match(status.textContent, /Обновляем/);
  win.MediaHubLibraryLoaded(); win.MediaHubLibraryDrawn(0, '');
  assert.equal(status.textContent, 'Показано материалов: 0');
});

function loader() {
  const elements = { q: { value: '' }, gb: {}, so: {} };
  const requests = [], events = [], draws = [];
  const win = { MediaHubLibraryPending: () => events.push('pending'),
    MediaHubLibraryLoaded: () => events.push('loaded'), MediaHubLibraryError: () => events.push('error') };
  const ctx = vm.createContext({ ALL: [], LIBSEQ: 0, LIBQUERY: null, window: win,
    $: id => elements[id], draw: () => draws.push([...ctx.ALL]),
    fetch: url => new Promise((resolve, reject) => requests.push({ url, resolve: body => resolve({ ok: true, json: async () => body }), reject })),
    setTimeout: fn => { ctx.timer = fn; return 1; }, clearTimeout: () => { ctx.timer = null; },
  });
  vm.runInContext(`${libCode}\n${inputCode}`, ctx);
  return { ctx, elements, requests, events, draws };
}

test('latest query wins even if earlier responses finish late or user reverts input', async () => {
  const f = loader();
  f.elements.q.value = 'first'; const first = f.ctx.lib();
  f.elements.q.value = 'second'; f.elements.q.oninput();
  f.elements.q.value = 'first'; f.elements.q.oninput();
  f.requests[0].resolve(['old']); await first;
  assert.equal(f.draws.length, 0);
  f.ctx.timer();
  assert.equal(f.requests.length, 2);
  f.requests[1].resolve(['current']); await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(f.draws, [['current']]);
  assert.equal(f.ctx.LIBQUERY, 'first');
  assert.equal(f.events.at(-1), 'loaded');
});

test('reset cancels debounce; stale or malformed responses do not replace current results', async () => {
  const f = loader();
  f.elements.q.value = 'old'; const old = f.ctx.lib();
  f.elements.q.value = ''; f.elements.q.oninput();
  f.ctx.searchNow(); assert.equal(f.ctx.timer, null);
  f.requests[1].resolve(['reset']); await new Promise(resolve => setImmediate(resolve));
  f.requests[0].resolve(['old']); await old;
  assert.deepEqual(f.draws, [['reset']]);
  const invalid = f.ctx.lib(); f.requests[2].resolve({ error: 'oops' }); await invalid;
  assert.deepEqual(f.draws, [['reset']]); assert.equal(f.events.at(-1), 'error');
  const failed = f.ctx.lib(); f.requests[3].reject(Error('network')); await failed;
  assert.deepEqual(f.draws, [['reset']]); assert.equal(f.events.at(-1), 'error');
});
