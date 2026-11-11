import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
const source = await readFile(new URL('../ui/reader-progress.js', import.meta.url), 'utf8');
const { setupProgressConflict, createProgressSaver } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
const flush = () => new Promise(resolve => setImmediate(resolve));

function fixture(fetcher, options = {}) {
  const elements = Object.fromEntries(['reader-conflict', 'reader-conflict-pending', 'reader-conflict-saved', 'reader-conflict-check', 'reader-conflict-apply']
    .map(id => [id, { textContent: '', hidden: true, disabled: false, focus() { this.focused = true; }, addEventListener(_type, handler) { this.click = handler; } }]));
  const doc = { getElementById: id => elements[id] };
  const panel = setupProgressConflict({ doc, itemId: '42', getSlug: () => 'example', getIdentity: () => 'd'.repeat(64),
    getChapters: () => [{ id: '1', label: '<Первая>' }, { id: '2', label: 'Вторая' }], fetcher,
    confirm: options.confirm ?? (() => false), onResolve: options.onResolve ?? (() => false), onStart: options.onStart });
  return { elements, panel, button: elements['reader-conflict-check'], apply: elements['reader-conflict-apply'], pending: elements['reader-conflict-pending'], saved: elements['reader-conflict-saved'] };
}

test('compare displays pending and fetched values without writes or adopting a token', async () => {
  const requests = [];
  const f = fixture(async (...args) => {
    requests.push(args);
    return { ok: true, json: async () => ({ progress_save_allowed: true, progress_slug: 'example', progress_identity: 'd'.repeat(64),
      progress_snapshot: 'not adopted', chapters: [{ id: '2', label: 'Вторая' }], progress: { cid: '2', page: 3 } }) };
  });
  f.panel.update({ cid: '1', page: 0 }); f.panel.show();
  assert.equal(f.elements['reader-conflict'].hidden, false);
  assert.equal(f.pending.textContent, 'Позиция этой вкладки (сохранение не подтверждено): <Первая> (ID 1), страница 1.');
  await f.button.click();
  assert.match(f.saved.textContent, /На момент проверки: Вторая \(ID 2\), страница 4/);
  assert.equal(f.apply.disabled, true); // malformed snapshot cannot enable replacement
  assert.deepEqual(requests, [['/api/manga/42']]);
  f.panel.update({ cid: '2', page: 1 });
  assert.match(f.pending.textContent, /Вторая \(ID 2\), страница 2/);
  assert.match(f.saved.textContent, /На момент проверки/);
});

test('reject mismatched identity, handle missing, invalid or unavailable progress', async () => {
  let result = { progress_save_allowed: false, progress_slug: 'other', progress: { cid: '1', page: 0 } };
  let fail = false;
  const f = fixture(async () => { if (fail) throw Error('offline'); return { ok: true, json: async () => result }; });
  f.panel.show();
  assert.match(f.pending.textContent, /Не удалось определить/);
  await f.button.click(); assert.match(f.saved.textContent, /идентичность/);
  result = { progress_save_allowed: true, progress_slug: 'example', progress_identity: 'd'.repeat(64), progress: null };
  await f.button.click(); assert.match(f.saved.textContent, /Сохранённой позиции нет/);
  result.progress = { cid: '<script>', page: -1 };
  await f.button.click(); assert.match(f.saved.textContent, /неизвестный формат/);
  result.progress = { cid: 'missing', page: 0 };
  await f.button.click(); assert.match(f.saved.textContent, /Глава \(ID missing\), страница 1/);
  fail = true; await f.button.click(); assert.match(f.saved.textContent, /Не удалось проверить/);
  assert.equal(f.button.disabled, false);
});

test('repeated clicks do not overlap, and latest pending position remains available', async () => {
  let resolve, calls = 0;
  const f = fixture(() => { calls++; return new Promise(done => { resolve = done; }); });
  f.panel.update({ cid: '1', page: 0 }); f.panel.show();
  const first = f.button.click(); f.button.click();
  assert.equal(calls, 1); assert.equal(f.button.disabled, true);
  f.panel.update({ cid: '2', page: 5 });
  resolve({ ok: true, json: async () => ({ progress_save_allowed: true, progress_slug: 'example', progress_identity: 'd'.repeat(64), progress: null }) });
  await first;
  assert.match(f.pending.textContent, /Вторая \(ID 2\), страница 6/);
  assert.equal(f.button.disabled, false);
});

test('conflict retains latest queued position, continues tracking without retrying', async () => {
  const positions = []; let reject, calls = 0;
  const saver = createProgressSaver({ status: () => {}, onPending: p => positions.push(p), send: () => {
    calls++; return new Promise((_resolve, fail) => { reject = fail; });
  } });
  saver.submit({ cid: '1', page: 0 }); saver.submit({ cid: '2', page: 1 });
  reject(Object.assign(Error('conflict'), { code: 'identity-conflict' })); await flush();
  assert.deepEqual(positions.at(-1), { cid: '2', page: 1 });
  saver.submit({ cid: '3', page: 2 }); saver.retry(); await flush();
  assert.deepEqual(positions.at(-1), { cid: '3', page: 2 }); assert.equal(calls, 1);
});

test('replacement requires a valid comparison and explicit confirmation', async () => {
  const calls = []; let approved = false, starts = 0;
  const f = fixture(async () => ({ ok: true, json: async () => ({ progress_save_allowed: true,
    progress_slug: 'example', progress_identity: 'd'.repeat(64), progress_snapshot: 'a'.repeat(64), progress: { cid: '2', page: 3 }, chapters: [] }) }),
    { confirm: text => { calls.push(text); return approved; }, onResolve: (...args) => { calls.push(args); return true; },
      onStart: () => { starts++; } });
  const position = { cid: '1', page: 0 }; f.panel.update(position); f.panel.show();
  assert.equal(f.apply.disabled, true); f.apply.click(); assert.equal(calls.length, 0);
  await f.button.click(); assert.equal(f.apply.disabled, false);
  f.apply.click(); assert.equal(calls.length, 1); assert.match(calls[0], /Заменить сохранённую позицию/);
  assert.equal(f.elements['reader-conflict'].hidden, false); assert.equal(starts, 0);
  approved = true; f.apply.click();
  assert.deepEqual(calls[2], ['a'.repeat(64), position]);
  assert.equal(f.elements['reader-conflict'].hidden, true); assert.equal(f.apply.disabled, true); assert.equal(starts, 1);
});

test('changed pending position invalidates comparison, including while fetch is in flight', async () => {
  let resolve;
  const result = { progress_save_allowed: true, progress_slug: 'example', progress_identity: 'd'.repeat(64), progress_snapshot: 'b'.repeat(64), progress: null };
  const f = fixture(() => new Promise(done => { resolve = done; }), { confirm: () => true, onResolve: () => { throw Error('must not save'); } });
  f.panel.update({ cid: '1', page: 0 }); f.panel.show();
  let check = f.button.click(); f.panel.invalidate();
  resolve({ ok: true, json: async () => result }); await check;
  assert.equal(f.apply.disabled, true); assert.match(f.saved.textContent, /проверьте ещё раз/);
  check = f.button.click(); resolve({ ok: true, json: async () => result }); await check;
  assert.equal(f.apply.disabled, false);
  f.panel.update({ cid: '2', page: 0 });
  assert.equal(f.apply.disabled, true); assert.match(f.saved.textContent, /изменилась/);
  f.apply.click();
});

test('queue resumes only the exact up-to-date pending object and token preparation runs once', async () => {
  const sent = [], statuses = [], changes = [], pending = [];
  let reject;
  const saver = createProgressSaver({ status: s => statuses.push(s), onDirty: d => changes.push(d), onPending: p => pending.push(p),
    send: p => { sent.push(p); return new Promise((_resolve, fail) => { reject = fail; }); } });
  const a = { cid: '1', page: 0 }; saver.submit(a);
  reject(Object.assign(Error('conflict'), { code: 'identity-conflict' })); await flush();
  let prepared = 0;
  assert.equal(saver.resolveConflict({ ...a }, () => prepared++), false);
  saver.markDirty();
  assert.equal(saver.resolveConflict(a, () => prepared++), false); // scroll not yet submitted
  const b = { cid: '2', page: 1 }; saver.submit(b);
  assert.equal(saver.resolveConflict(a, () => prepared++), false);
  assert.equal(saver.resolveConflict(b, () => prepared++), true);
  assert.equal(saver.resolveConflict(b, () => prepared++), false);
  assert.equal(prepared, 1); assert.deepEqual(sent, [a, b]); assert.deepEqual(changes, [true]);
  reject(Object.assign(Error('conflict again'), { code: 'identity-conflict' })); await flush();
  assert.equal(statuses.at(-1), 'conflict'); assert.deepEqual(pending.at(-1), b);
});

test('failed resolution requires a fresh comparison, never retries automatically', async () => {
  let resolutions = 0;
  const f = fixture(async () => ({ ok: true, json: async () => ({ progress_save_allowed: true,
    progress_slug: 'example', progress_identity: 'd'.repeat(64), progress_snapshot: 'c'.repeat(64), progress: null }) }),
    { confirm: () => true, onResolve: () => { resolutions++; return false; } });
  f.panel.update({ cid: '1', page: 0 }); f.panel.show();
  await f.button.click(); assert.equal(f.apply.disabled, false);
  f.apply.click(); f.apply.click();
  assert.equal(resolutions, 1); assert.equal(f.apply.disabled, true);
  assert.equal(f.elements['reader-conflict'].hidden, false); assert.match(f.saved.textContent, /Проверьте/);
});

test('same-position scroll preserves the reviewed selection without weakening change detection', async () => {
  const updates = []; let reject, sent = 0;
  const saver = createProgressSaver({ status: () => {}, onPending: p => updates.push(p), send: () => {
    sent++; return new Promise((_resolve, fail) => { reject = fail; });
  } });
  const original = { id: '42', slug: 'example', cid: '1', page: 0 };
  saver.submit(original); reject(Object.assign(Error('conflict'), { code: 'identity-conflict' })); await flush();
  saver.markDirty(); saver.submit({ ...original });
  assert.equal(updates.at(-1), original);
  assert.equal(saver.resolveConflict(original, () => {}), true);
  assert.equal(sent, 2);
});

test('folder identity changes or missing identity cannot be approved', async () => {
  let identity = 'e'.repeat(64), saves = 0;
  const f = fixture(async () => ({ ok: true, json: async () => ({ progress_save_allowed: true,
    progress_slug: 'example', progress_identity: identity, progress_snapshot: 'f'.repeat(64), progress: null }) }),
    { confirm: () => true, onResolve: () => { saves++; return true; } });
  f.panel.update({ cid: '1', page: 0 }); f.panel.show();
  for (identity of ['e'.repeat(64), undefined, 'invalid']) {
    await f.button.click(); assert.match(f.saved.textContent, /идентичность/);
    assert.equal(f.apply.disabled, true); f.apply.click();
  }
  assert.equal(saves, 0);
});
