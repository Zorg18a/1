import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const source = await readFile(new URL('../ui/game-library.js', import.meta.url), 'utf8');
const { gameLabels, sizeMatches, releaseTime, compareGames } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);

test('tags, site genres and engine are combined without duplicate labels', () => {
  assert.deepEqual(gameLabels({ genres: ['RPG', 'Drama'], tags: ['rpg', 'Свои', '<b>'], engine: 'RenPy' }),
    ['RPG', 'Drama', 'Свои', '<b>', 'RenPy']);
  assert.deepEqual(gameLabels({}), []);
});

test('size filters use binary units and treat zero as unknown', () => {
  const gib = 1024 ** 3;
  assert.equal(sizeMatches(0, 'small'), false);
  assert.equal(sizeMatches(0, 'unknown'), true);
  assert.equal(sizeMatches(gib - 1, 'small'), true);
  assert.equal(sizeMatches(gib, 'medium'), true);
  assert.equal(sizeMatches(10 * gib - 1, 'medium'), true);
  assert.equal(sizeMatches(10 * gib, 'large'), true);
});

test('updates precede other games in every sort and ties are deterministic', () => {
  const games = [
    { title: 'A', size: 100, g: { update: false, added: 9, release: '2025-01-01' } },
    { title: 'Z', size: 1, g: { update: true, added: 1, release: '01.01.2020' } },
    { title: 'B', size: 2, g: { update: true, added: 2, release: '01.01.2024' } },
  ];
  for (const mode of ['name', 'size', 'added', 'release', 'upd']) {
    const sorted = games.toSorted ? games.toSorted((a, b) => compareGames(a, b, mode)) : [...games].sort((a, b) => compareGames(a, b, mode));
    assert.deepEqual(sorted.map(x => x.g.update), [true, true, false]);
    assert.equal(sorted[0].title, 'B');
  }
  assert.equal(releaseTime('31.02.2024'), -Infinity);
  assert.equal(releaseTime('unknown'), -Infinity);
  assert.ok(releaseTime('01.01.2024') > releaseTime('01.01.2020'));
});

test('tag form sends a protected request, reports errors and emits saved tags', async () => {
  const tagSource = await readFile(new URL('../ui/game-tags.js', import.meta.url), 'utf8');
  const { setupGameTags } = await import(`data:text/javascript;base64,${Buffer.from(tagSource).toString('base64')}`);
  const original = Object.fromEntries(['window', 'document', 'fetch', 'CustomEvent'].map(k => [k, globalThis[k]]));
  const listeners = {}, fields = { input: { value: '' }, button: { disabled: false }, status: { textContent: '' } };
  const form = { addEventListener(type, fn) { this[type] = fn; },
    querySelector(selector) { return selector === 'input' ? fields.input : selector === 'button' ? fields.button : fields.status; } };
  let inserted = false, request, saved, fail = true;
  const panel = { querySelector(s) { return s === '.game-tags-form' ? (inserted ? form : null) : {}; },
    insertBefore() { inserted = true; } };
  try {
    globalThis.window = { addEventListener: (type, fn) => { listeners[type] = fn; },
      dispatchEvent: event => { if (event.type === 'mediahub:tags-saved') saved = event.detail; } };
    globalThis.document = { querySelector: () => panel, createElement: () => form };
    globalThis.CustomEvent = class { constructor(type, init) { this.type = type; this.detail = init.detail; } };
    globalThis.fetch = async (url, options) => { request = { url, ...options }; return fail
      ? { ok: false, json: async () => ({ error: 'Ошибка' }) }
      : { ok: true, json: async () => ({ tags: ['RPG', 'Моё'] }) }; };
    setupGameTags();
    listeners['mediahub:game-panel']({ detail: { id: 4, g: { tags: ['RPG'] } } });
    assert.equal(fields.input.value, 'RPG');
    fields.input.value = 'RPG, Моё';
    await form.submit({ preventDefault() {} });
    assert.equal(fields.status.textContent, 'Ошибка');
    assert.equal(fields.button.disabled, false);
    assert.equal(saved, undefined);
    fail = false;
    await form.submit({ preventDefault() {} });
    assert.equal(request.url, '/api/game/tags');
    assert.equal(request.headers['X-MH'], '1');
    assert.deepEqual(JSON.parse(request.body), { id: 4, tags: ['RPG', 'Моё'] });
    assert.deepEqual(saved, { id: 4, tags: ['RPG', 'Моё'] });
    assert.equal(fields.status.textContent, 'Теги сохранены');
  } finally {
    for (const [key, value] of Object.entries(original)) {
      if (value === undefined) delete globalThis[key]; else globalThis[key] = value;
    }
  }
});
