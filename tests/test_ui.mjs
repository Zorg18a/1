import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

async function load(name) {
  const source = await readFile(new URL(`../ui/${name}.js`, import.meta.url), 'utf8');
  return import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
}

test('display preferences validate and persist without throwing on blocked storage', async () => {
  const { normalizePreferences, readPreferences, savePreferences } = await load('preferences');
  const valid = { theme: 'light', size: 'large', contrast: 'high', hotkeys: false };
  let value;
  const store = { getItem: () => value, setItem: (_key, data) => { value = data; } };
  assert.equal(savePreferences(store, valid), true);
  assert.deepEqual(readPreferences(store), valid);
  assert.deepEqual(normalizePreferences({ theme: 'invalid', size: 10, hotkeys: 'false' }),
    { theme: 'dark', size: 'normal', contrast: 'normal', hotkeys: true });
  assert.equal(savePreferences({ setItem() { throw Error('blocked'); } }, valid), false);
  assert.equal(readPreferences({ getItem() { throw Error('blocked'); } }).theme, 'dark');
  assert.equal(readPreferences({ getItem() { return '{'; } }).theme, 'dark');
});

test('session notifications are bounded, newest first and clearable', async () => {
  const { createHistory } = await load('notifications');
  const history = createHistory();
  for (let i = 0; i < 205; i++) history.add({ message: String(i) });
  assert.equal(history.list().length, 200);
  assert.equal(history.list()[0].message, '204');
  assert.equal(history.list()[199].message, '5');
  history.list().pop();
  assert.equal(history.list().length, 200);
  history.clear();
  assert.equal(history.list().length, 0);
});

test('job completions are reported once and initial state is not replayed', async () => {
  const { createJobTracker } = await load('job-events');
  const track = createJobTracker();
  assert.deepEqual(track([{ id: 1, title: 'A', status: 'в очереди' }]), []);
  assert.deepEqual(track([{ id: 1, title: 'A', status: 'готово' }]), ['A: готово']);
  assert.deepEqual(track([{ id: 1, title: 'A', status: 'готово' }]), []);
  assert.deepEqual(track([{ id: 1, title: 'A', status: 'готово' }, { id: 2, title: 'B', status: 'ошибка' }]), ['B: ошибка']);
});

test('G sequences navigate and unrelated keys reset the prefix', async () => {
  const { nextShortcut } = await load('hotkeys');
  assert.deepEqual(nextShortcut(false, 'G'), { armed: true, route: null });
  for (const [key, route] of Object.entries({ l: 'library', i: 'inbox', d: 'downloads', g: 'games', s: 'settings' })) {
    assert.deepEqual(nextShortcut(true, key), { armed: false, route });
  }
  assert.deepEqual(nextShortcut(true, 'x'), { armed: false, route: null });
  assert.deepEqual(nextShortcut(false, 'l'), { armed: false, route: null });
});
