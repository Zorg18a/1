import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
const source = await readFile(new URL('../ui/library-playback-hint.js', import.meta.url), 'utf8');
const { setupLibraryPlaybackHint } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
class Element {
  constructor() { this.attrs = {}; }
  getAttribute(name) { return this.attrs[name] ?? null; }
  setAttribute(name, value) { this.attrs[name] = value; }
}
function fixture() {
  let changed, options, disconnected = false;
  const library = new Element(); library.previews = [];
  library.before = node => { library.hint = node; };
  library.querySelectorAll = () => library.previews;
  class Observer {
    constructor(fn) { changed = fn; }
    observe(node, opts) { assert.equal(node, library); options = opts; }
    disconnect() { disconnected = true; }
  }
  const doc = { getElementById: id => id === 'lib' ? library : null, createElement: () => new Element() };
  const stop = setupLibraryPlaybackHint({ doc, Observer });
  return { library, changed, options, stop, isDisconnected: () => disconnected };
}
function card(title) {
  const cover = new Element(), preview = new Element();
  const card = { querySelector: selector => selector === 'a.cv' ? cover : { textContent: title } };
  preview.closest = () => card;
  return { cover, preview };
}

test('describes both actions, preserves existing attributes and updates after redraw', () => {
  const f = fixture();
  assert.match(f.library.hint.textContent, /не использует позицию предпросмотра/);
  assert.match(f.library.hint.textContent, /только в этом браузере/);
  assert.deepEqual(f.options, { childList: true, subtree: true });
  const first = card('<title>'); first.cover.setAttribute('href', '/f/1');
  first.cover.setAttribute('aria-describedby', 'existing'); first.preview.setAttribute('href', '/p/1');
  f.library.previews = [first.preview]; f.changed(); f.changed();
  assert.equal(first.cover.getAttribute('aria-label'), 'Открыть файл напрямую: <title>');
  assert.equal(first.cover.getAttribute('aria-describedby'), 'existing library-playback-hint');
  assert.equal(first.preview.getAttribute('aria-describedby'), 'library-playback-hint');
  assert.equal(first.cover.getAttribute('href'), '/f/1'); assert.equal(first.preview.getAttribute('href'), '/p/1');
  const second = card('Audio'); f.library.previews = [second.preview]; f.changed();
  assert.equal(second.cover.getAttribute('aria-label'), 'Открыть файл напрямую: Audio');
  f.stop(); assert.equal(f.isDisconnected(), true);
});

test('is safe on pages without a library or cards without a cover', () => {
  assert.equal(setupLibraryPlaybackHint({ doc: { getElementById: () => null }, Observer: class {} }), undefined);
  const f = fixture(); f.library.previews = [{ closest: () => null }];
  assert.doesNotThrow(() => f.changed());
});
