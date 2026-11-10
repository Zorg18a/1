import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const source = await readFile(new URL('../ui/player-subtitles.js', import.meta.url), 'utf8');
const { setupSubtitleSelector, cycleSubtitles } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
const track = (language, label, kind = 'subtitles', mode = 'disabled') => ({ language, label, kind, mode });
class Tracks extends Array {
  listeners = {};
  addEventListener(type, fn) { this.listeners[type] = fn; }
  emit(type) { this.listeners[type]?.(); }
}
function fixture(initial = [], saved = null, expected = initial.length, blocked = false) {
  const tracks = new Tracks(...initial), store = new Map();
  if (saved !== null) store.set('mediahub.player.subtitles.v1.7', saved);
  const storage = { getItem: key => { if (blocked) throw Error('blocked'); return store.get(key) ?? null; },
    setItem: (key, value) => { if (blocked) throw Error('blocked'); store.set(key, value); } };
  const select = { children: [], value: '', addEventListener(type, fn) { this[type] = fn; },
    replaceChildren(...children) { this.children = children; } };
  const container = { hidden: true };
  const doc = { createElement: () => ({}) };
  const media = { textTracks: tracks };
  const changed = setupSubtitleSelector({ doc, media, select, container, storage, itemId: '7', expected });
  return { tracks, store, select, container, media, changed };
}

test('selector shows real subtitle tracks and handles delayed insertion', () => {
  const f = fixture([], null, 1);
  assert.equal(f.container.hidden, true);
  f.tracks.push(track('en', 'English'), track('', 'Metadata', 'metadata'));
  f.tracks.emit('addtrack');
  assert.equal(f.container.hidden, false);
  assert.deepEqual(f.select.children.map(x => x.textContent), ['Выключены', 'English']);
  assert.equal(f.select.value, '-1');
  f.tracks.splice(0, 1); f.tracks.emit('removetrack');
  assert.equal(f.container.hidden, true);
});

test('select, native change and C keep the control and preferences in sync', () => {
  const f = fixture([track('ru', 'Русский'), track('en', 'English')]);
  f.select.value = '1'; f.select.change();
  assert.deepEqual(Array.from(f.tracks, t => t.mode), ['disabled', 'showing']);
  assert.deepEqual(JSON.parse(f.store.get('mediahub.player.subtitles.v1.7')),
    { mode: 'track', language: 'en', label: 'English' });
  f.tracks[1].mode = 'disabled'; f.tracks[0].mode = 'showing'; f.tracks.emit('change');
  assert.equal(f.select.value, '0');
  assert.equal(JSON.parse(f.store.get('mediahub.player.subtitles.v1.7')).language, 'ru');
  assert.equal(cycleSubtitles(f.media), 'Субтитры: English'); f.changed();
  assert.equal(f.select.value, '1');
  assert.equal(cycleSubtitles(f.media), 'Субтитры выключены'); f.changed();
  assert.equal(f.select.value, '-1');
  assert.deepEqual(JSON.parse(f.store.get('mediahub.player.subtitles.v1.7')), { mode: 'off' });
});

test('preference restores by identity rather than index and waits for tracks', () => {
  const saved = JSON.stringify({ mode: 'track', language: 'en', label: 'English' });
  const f = fixture([], saved, 2);
  f.tracks.push(track('en', 'English')); f.tracks.emit('addtrack');
  assert.equal(f.tracks[0].mode, 'disabled');
  f.tracks.push(track('ru', 'Русский')); f.tracks.emit('addtrack');
  assert.equal(f.tracks[0].mode, 'showing');
  assert.equal(f.select.value, '0');
  const off = fixture([track('en', 'English', 'subtitles', 'showing')], JSON.stringify({ mode: 'off' }));
  assert.equal(off.tracks[0].mode, 'disabled'); assert.equal(off.select.value, '-1');
});

test('ambiguous or missing saved tracks leave browser choice unchanged', () => {
  const saved = JSON.stringify({ mode: 'track', language: 'en', label: 'English' });
  const f = fixture([track('en', 'English'), track('en', 'English')], saved);
  assert.deepEqual(Array.from(f.tracks, t => t.mode), ['disabled', 'disabled']);
  const missing = fixture([track('ru', 'Русский', 'subtitles', 'showing')], saved);
  assert.equal(missing.tracks[0].mode, 'showing');
  assert.equal(missing.select.value, '0');
});

test('blocked or corrupt storage and invalid selections do not break controls', () => {
  const f = fixture([track('en', '<img>')], '{bad json');
  assert.equal(f.select.children[1].textContent, '<img>');
  f.select.value = '99'; f.select.change();
  assert.equal(f.tracks[0].mode, 'disabled');
  assert.equal(f.select.value, '-1');
  const blocked = fixture([track('en', 'English')], null, 1, true);
  blocked.select.value = '0'; blocked.select.change();
  assert.equal(blocked.tracks[0].mode, 'showing');
  assert.equal(blocked.select.value, '0');
});
