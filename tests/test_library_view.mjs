import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const source = await readFile(new URL('../ui/library-view.js', import.meta.url), 'utf8');
const { normalizeLibraryView, readLibraryView, saveLibraryView, setupLibraryView } =
  await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
const defaults = { sort: 'added', group: 'author', kind: '' };

test('validates each preference and ignores invalid or blocked storage', () => {
  assert.deepEqual(normalizeLibraryView({ sort: 'title', group: '', kind: 'audio' }),
    { sort: 'title', group: '', kind: 'audio' });
  assert.deepEqual(normalizeLibraryView({ sort: 'x', group: 5, kind: 'script' }), defaults);
  assert.deepEqual(normalizeLibraryView(null), defaults);
  assert.deepEqual(readLibraryView({ getItem() { return '{'; } }), defaults);
  assert.deepEqual(readLibraryView({ getItem() { throw Error('blocked'); } }), defaults);
  assert.equal(saveLibraryView({ setItem() { throw Error('blocked'); } }, defaults), false);
  let stored;
  const storage = { setItem: (_key, value) => { stored = value; }, getItem: () => stored };
  assert.equal(saveLibraryView(storage, { sort: 'size', group: 'topic', kind: 'video', query: 'private' }), true);
  assert.deepEqual(readLibraryView(storage), { sort: 'size', group: 'topic', kind: 'video' });
  assert.doesNotMatch(stored, /private|query/);
});

test('restores selections, persists changes and reports storage failure', () => {
  const old = Object.fromEntries(['window', 'document'].map(key => [key, globalThis[key]]));
  const handlers = {}, elements = {
    so: { value: '', addEventListener: (_type, fn) => { handlers.sort = fn; } },
    gb: { value: '', addEventListener: (_type, fn) => { handlers.group = fn; } },
  };
  const warning = { setAttribute(name, value) { this[name] = value; } };
  const tools = { append(node) { assert.equal(node, warning); } };
  let value = JSON.stringify({ sort: 'title', group: 'topic', kind: 'manga' }), selected;
  let blocked = false;
  const storage = { getItem: () => value, setItem(_key, next) { if (blocked) throw Error(); value = next; } };
  try {
    globalThis.document = { getElementById: id => elements[id], createElement: () => warning,
      querySelector: () => tools };
    globalThis.window = { localStorage: storage, setK: kind => { selected = kind; },
      addEventListener: (type, fn) => { handlers[type] = fn; } };
    setupLibraryView();
    assert.equal(elements.so.value, 'title');
    assert.equal(elements.gb.value, 'topic');
    assert.equal(selected, 'manga');
    assert.equal(warning.hidden, true);
    assert.equal(warning.role, 'status');
    elements.so.value = 'size'; handlers.sort();
    handlers['mediahub:library-kind']({ detail: 'audio' });
    assert.deepEqual(JSON.parse(value), { sort: 'size', group: 'topic', kind: 'audio' });
    blocked = true; elements.gb.value = ''; handlers.group();
    assert.equal(warning.hidden, false);
    blocked = false; handlers.group();
    assert.equal(warning.hidden, true);
  } finally {
    for (const [key, value] of Object.entries(old)) {
      if (value === undefined) delete globalThis[key]; else globalThis[key] = value;
    }
  }
});
