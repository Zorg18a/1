import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';

const html = await readFile(new URL('../ui/index.html', import.meta.url), 'utf8');
const start = html.indexOf('function draw(){');
const end = html.indexOf("\n['gb','so'].forEach", start);
assert.ok(start >= 0 && end > start, 'library draw code is available');
const drawCode = html.slice(start, end);
const escapeCode = html.match(/^const esc=.*$/m)?.[0];
assert.ok(escapeCode, 'library escaping is available');

function render(items, { filter = '', group = '', search = '' } = {}) {
  const elements = { so: { value: 'title' }, gb: { value: group }, q: { value: search },
    chips: { innerHTML: '' }, lib: { innerHTML: '' } };
  const context = { ALL: items.map(item => ({ author: '', topic: '', size: 0, cover: '', ...item })),
    FK: filter, L: [], LIBQUERY: search, window: {}, $: id => elements[id], B: () => '0 Б', I: () => '', IC: { video: '' } };
  vm.runInNewContext(`${escapeCode}\n${drawCode}\ndraw();`, context);
  return elements.lib.innerHTML;
}
const cards = html => html.match(/<article class="c">[\s\S]*?<\/article>/g) || [];

test('available audio and video expose a separate preview while primary links stay direct', () => {
  const output = render([
    { id: 1, kind: 'audio', title: 'Audio', open: '/f/1', missing: false },
    { id: 2, kind: 'video', title: 'Video', open: '/f/2', missing: false },
    { id: 3, kind: 'manga', title: 'Manga', open: '/m/3', missing: false },
    { id: 4, kind: 'audio', title: 'Missing', open: '/f/4', missing: true },
    { id: 5, kind: 'game', title: 'Game', open: '/f/5', missing: false },
  ]);
  const items = cards(output);
  assert.equal(items.length, 5);
  for (const id of [1, 2]) {
    const card = items.find(value => value.includes(`href="/f/${id}"`));
    assert.match(card, new RegExp(`href="/p/${id}"`));
    assert.match(card, /Предпросмотр плеера:/);
    assert.match(card, /target="_blank" rel="noopener"/);
  }
  assert.equal((output.match(/class="btn player-preview"/g) || []).length, 2);
  assert.ok(items.find(value => value.includes('href="/m/3"')));
  assert.doesNotMatch(items.find(value => value.includes('href="/f/4"')), /player-preview/);
});

test('untrusted ids are rejected and titles are escaped in the preview label', () => {
  const output = render([
    { id: 1, kind: 'video', title: '"<img src=x>', open: '/f/1' },
    { id: '1" onclick="evil()', kind: 'video', title: 'Bad id', open: '/f/2' },
    { id: Number.MAX_SAFE_INTEGER + 1, kind: 'audio', title: 'Unsafe integer', open: '/f/3' },
    { id: 0, kind: 'audio', title: 'Zero', open: '/f/4' },
  ]);
  assert.equal((output.match(/class="btn player-preview"/g) || []).length, 1);
  const good = cards(output).find(value => value.includes('href="/p/1"'));
  assert.match(good, /&quot;&lt;img src=x&gt;/);
  assert.doesNotMatch(good, /<img src=x>/);
  assert.doesNotMatch(output, /href="\/p\/1" onclick=/);
});

test('a selected type remains available when search has no matching items', () => {
  const elements = { so: { value: 'title' }, gb: { value: '' }, q: { value: 'nothing' },
    chips: { innerHTML: '' }, lib: { innerHTML: '' } };
  const context = { ALL: [], FK: 'video', L: [], LIBQUERY: 'nothing', window: {}, $: id => elements[id], B: () => '0 Б', I: () => '', IC: {} };
  vm.runInNewContext(`${escapeCode}\n${drawCode}\ndraw()`, context);
  assert.equal(context.FK, 'video');
  assert.match(elements.chips.innerHTML, /aria-pressed="true"[^>]*>Видео<span>0/);
  assert.match(elements.lib.innerHTML, /выбранному типу/);
  elements.q.value = '';
  vm.runInContext('draw()', context);
  assert.match(elements.lib.innerHTML, /Показать все материалы/);
});

test('the preview link follows library filtering and grouping', () => {
  const items = [{ id: 1, kind: 'video', title: 'Video', author: 'Creator', open: '/f/1' },
    { id: 2, kind: 'audio', title: 'Audio', author: 'Creator', open: '/f/2' }];
  const output = render(items, { filter: 'audio', group: 'author' });
  assert.match(output, /<h2>Creator/);
  assert.match(output, /href="\/p\/2"/);
  assert.doesNotMatch(output, /href="\/p\/1"/);
});
