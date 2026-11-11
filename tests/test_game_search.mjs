import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';
const dataUrl = text => `data:text/javascript;base64,${Buffer.from(text).toString('base64')}`;
const { setupGameSearch } = await import(dataUrl(await readFile(new URL('../ui/game-search.js', import.meta.url), 'utf8')));
const gameLib = await import(dataUrl(await readFile(new URL('../ui/game-library.js', import.meta.url), 'utf8')));
const html = await readFile(new URL('../ui/index.html', import.meta.url), 'utf8');
const drawCode = html.slice(html.indexOf('function drawGames(){'), html.indexOf('\nfunction fillPanel('));
const loadCode = html.match(/^async function loadGames\(\).*$/m)?.[0];
const resetCode = html.match(/function resetGameFilters\(\).*?\}\$\('gq'\)/)?.[0]?.slice(0, -7);
assert.ok(drawCode && loadCode && resetCode);

class Element {
  constructor() { this.children = []; this.handlers = {}; this.value = ''; this.classList = { contains: () => true }; }
  setAttribute(k, v) { this[k] = v; }
  append(...nodes) { this.children.push(...nodes); }
  after(node) { this.inserted = node; }
  addEventListener(type, fn) { this.handlers[type] = fn; }
  focus() { this.focused = true; }
}

test('counts filtered games and reports loading errors without claiming old results are current', () => {
  const nodes = { gq: new Element(), 'v-games': new Element(), 'gtab-lib': new Element() };
  const tools = new Element(), calls = [];
  const doc = { getElementById: id => nodes[id], createElement: () => new Element(), querySelector: () => tools };
  const win = { loadGames: () => calls.push('load'), resetGameFilters: () => calls.push('reset') };
  setupGameSearch({ doc, win });
  const [reset, retry, status] = tools.inserted.children;
  assert.match(nodes.gq['aria-label'], /тегу или движку/);
  assert.equal(status['aria-live'], 'polite');
  assert.deepEqual(calls, []);
  win.MediaHubGamesDrawn(0, 0); assert.match(status.textContent, /Обновляем/);
  win.MediaHubGamesLoaded(); win.MediaHubGamesDrawn(1, 2);
  assert.equal(status.textContent, 'Показано игр: 1 из 2');
  win.MediaHubGamesPending(); win.MediaHubGamesError(); win.MediaHubGamesDrawn(0, 0);
  assert.match(status.textContent, /прежние результаты/);
  reset.handlers.click(); assert.equal(nodes.gq.focused, true);
  retry.handlers.click(); assert.deepEqual(calls, ['reset', 'load']);
});

test('open games tab requests a fresh load if setup missed initial events', () => {
  const nodes = { gq: new Element(), 'v-games': new Element(), 'gtab-lib': new Element() };
  nodes['v-games'].classList.contains = () => false; nodes['gtab-lib'].classList.contains = () => false;
  let count = 0;
  setupGameSearch({ doc: { getElementById: id => nodes[id], createElement: () => new Element(), querySelector: () => new Element() },
    win: { loadGames: () => count++ } });
  assert.equal(count, 1);
});

function drawFixture() {
  const nodes = Object.fromEntries(['gq', 'gso', 'gsize', 'gchips', 'genl', 'gens', 'ggrid'].map(id => [id, new Element()]));
  nodes.gso.value = 'size';
  const games = [
    { id: 1, title: 'CollegeTraits', kind: 'game', size: 1024 ** 3, g: { developer: 'Dev', downloaded: true, update: false, genres: ['RPG'], tags: ['Моё'], engine: 'RenPy' } },
    { id: 2, title: 'Other', kind: 'game', size: 0, g: { developer: 'Second', downloaded: false, update: true, genres: ['RPG'], tags: ['Другое'], engine: '' } },
  ];
  let drawn;
  const ctx = vm.createContext({ GA: games, GF: 'all', GGEN: new Set(), GFILT: { all: 'Все', dl: 'Скачано', nodl: 'Не скачано', upd: 'Обновление' },
    window: { MediaHubGameLibrary: gameLib, MediaHubGamesDrawn: (n, total) => { drawn = [n, total]; } },
    $: id => nodes[id], esc: s => String(s), gdraw: x => `<article>${x.title}</article>`, Event: class { constructor(type) { this.type = type; } } });
  vm.runInContext(drawCode + '\n' + resetCode, ctx);
  nodes.gsize.dispatchEvent = () => { nodes.sizeChanged = true; ctx.drawGames(); };
  return { nodes, ctx, getDrawn: () => drawn };
}

test('count matches all filters, tag and engine search, status chips and reset preserve sort', () => {
  const f = drawFixture();
  f.ctx.drawGames(); assert.deepEqual(f.getDrawn(), [2, 2]);
  assert.match(f.nodes.gchips.innerHTML, /data-gf="all" aria-pressed="true"/);
  f.nodes.gq.value = 'College Traits'; f.ctx.drawGames(); assert.deepEqual(f.getDrawn(), [1, 2]);
  f.nodes.gq.value = 'renpy'; f.ctx.drawGames(); assert.deepEqual(f.getDrawn(), [1, 2]);
  f.nodes.gq.value = 'моё'; f.ctx.drawGames(); assert.deepEqual(f.getDrawn(), [1, 2]);
  f.ctx.GF = 'nodl'; f.ctx.GGEN.add('rpg'); f.nodes.gsize.value = 'medium'; f.nodes.gq.value = '';
  f.ctx.drawGames(); assert.deepEqual(f.getDrawn(), [0, 2]);
  f.ctx.resetGameFilters();
  assert.equal(f.nodes.gq.value, ''); assert.equal(f.nodes.gsize.value, ''); assert.equal(f.nodes.gso.value, 'size');
  assert.equal(f.ctx.GF, 'all'); assert.equal(f.ctx.GGEN.size, 0); assert.equal(f.nodes.sizeChanged, true);
  assert.deepEqual(f.getDrawn(), [2, 2]);
});

function loader() {
  const requests = [], events = [], draws = [];
  const ctx = vm.createContext({ GA: [], GSEQ: 0, GOPEN: 0,
    window: { MediaHubGamesPending: () => events.push('pending'), MediaHubGamesLoaded: () => events.push('loaded'), MediaHubGamesError: () => events.push('error') },
    fetch: url => new Promise((resolve, reject) => requests.push({ url, resolve: body => resolve({ ok: true, json: async () => body }), reject })),
    drawGames: () => draws.push(ctx.GA.map(game => game.id)),
  });
  vm.runInContext(loadCode, ctx);
  return { ctx, requests, events, draws };
}

test('newer game load wins, network and invalid responses preserve previous games', async () => {
  const f = loader();
  const first = f.ctx.loadGames(), second = f.ctx.loadGames();
  f.requests[1].resolve([{ id: 2, kind: 'game' }, { id: 3, kind: 'video' }]); await second;
  f.requests[0].resolve([{ id: 1, kind: 'game' }]); await first;
  assert.deepEqual(f.draws, [[2]]); assert.equal(f.events.at(-1), 'loaded');
  const bad = f.ctx.loadGames(); f.requests[2].resolve({ error: 'no' }); await bad;
  assert.equal(f.events.at(-1), 'error'); assert.deepEqual(f.draws, [[2]]);
  const failed = f.ctx.loadGames(); f.requests[3].reject(Error('offline')); await failed;
  assert.equal(f.events.at(-1), 'error'); assert.deepEqual(f.draws, [[2]]);
});
