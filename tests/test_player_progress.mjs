import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
const source = await readFile(new URL('../ui/player-progress.js', import.meta.url), 'utf8');
const { setupPlayerProgress } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
const identity = 'a'.repeat(64), key = 'mediahub.player.position.v1.7';

class Element {
  listeners = {}; currentTime = 0; duration = 120; ended = false; disabled = true; textContent = '';
  addEventListener(type, fn) { this.listeners[type] = fn; }
  emit(type) { this.listeners[type]?.(); }
}
function fixture({ initial, blocked = false, hash = identity, duration = 120 } = {}) {
  const data = new Map(initial === undefined ? [] : [[key, initial]]);
  const storage = { getItem(k) { if (blocked) throw Error('blocked'); return data.get(k) ?? null; },
    setItem(k, v) { if (blocked) throw Error('blocked'); data.set(k, v); },
    removeItem(k) { if (blocked) throw Error('blocked'); data.delete(k); } };
  const media = new Element(), status = new Element(), reset = new Element(), win = new Element();
  media.duration = duration;
  setupPlayerProgress({ media, status, reset, win, storage, itemId: '7', identity: hash });
  return { data, media, status, reset, win };
}
const position = (pos = 30, duration = 120, hash = identity) => JSON.stringify({ identity: hash, position: pos, duration });

test('restores same file after metadata without autoplay and ignores early events', () => {
  const f = fixture({ initial: position() });
  f.media.emit('pause'); assert.equal(f.data.get(key), position());
  assert.equal(f.reset.disabled, true);
  f.media.emit('loadedmetadata');
  assert.equal(f.media.currentTime, 30);
  assert.equal(f.reset.disabled, false);
  assert.match(f.status.textContent, /восстановлена/);
  f.media.currentTime = 35; f.media.emit('loadedmetadata');
  assert.equal(f.media.currentTime, 35);
});

test('seek, pause and pagehide save; ended and restart clear', () => {
  const f = fixture(); f.media.emit('loadedmetadata');
  f.media.currentTime = 20; f.media.emit('seeked');
  assert.deepEqual(JSON.parse(f.data.get(key)), { identity, position: 20, duration: 120 });
  f.media.currentTime = 22; f.media.emit('pause');
  assert.equal(JSON.parse(f.data.get(key)).position, 22);
  f.media.currentTime = 24; f.win.emit('pagehide');
  assert.equal(JSON.parse(f.data.get(key)).position, 24);
  f.reset.emit('click'); assert.equal(f.media.currentTime, 0); assert.equal(f.data.has(key), false);
  assert.match(f.status.textContent, /сброшена/);
  f.media.currentTime = 50; f.media.emit('seeked');
  f.media.ended = true; f.media.emit('ended');
  assert.equal(f.data.has(key), false);
});

test('timeupdate saves after play and is throttled', () => {
  const f = fixture(); f.media.emit('loadedmetadata');
  f.media.currentTime = 10; f.media.emit('timeupdate'); assert.equal(f.data.has(key), false);
  f.media.emit('play'); f.media.emit('timeupdate'); assert.equal(JSON.parse(f.data.get(key)).position, 10);
  f.media.currentTime = 12; f.media.emit('timeupdate'); assert.equal(JSON.parse(f.data.get(key)).position, 10);
  f.media.emit('pause'); assert.equal(JSON.parse(f.data.get(key)).position, 12);
});

test('different file, duration, corrupt or invalid values never restore', () => {
  for (const initial of [position(30, 120, 'b'.repeat(64)), position(30, 160), position(-1),
    position(120), JSON.stringify({ identity, position: '30', duration: 120 }), '{broken', 'x'.repeat(3000)]) {
    const f = fixture({ initial }); f.media.emit('loadedmetadata'); assert.equal(f.media.currentTime, 0, initial);
    assert.equal(f.data.get(key), initial);
  }
});

test('blocked storage, missing identity and unavailable metadata degrade safely', () => {
  const blocked = fixture({ blocked: true }); blocked.media.emit('loadedmetadata');
  assert.match(blocked.status.textContent, /Не удалось/);
  blocked.media.currentTime = 25; blocked.media.emit('seeked');
  assert.match(blocked.status.textContent, /Не удалось/);
  blocked.reset.emit('click'); assert.equal(blocked.media.currentTime, 0);
  assert.match(blocked.status.textContent, /Не удалось/);
  const missing = fixture({ hash: null }); missing.media.emit('loadedmetadata');
  assert.match(missing.status.textContent, /не удалось определить файл/);
  const unknown = fixture({ initial: position(), duration: Infinity });
  unknown.media.emit('loadedmetadata'); assert.equal(unknown.reset.disabled, true);
  assert.equal(unknown.data.get(key), position());
});
