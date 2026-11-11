import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
const source = await readFile(new URL('../ui/reader-progress.js', import.meta.url), 'utf8');
const { setupProgressConflict, createProgressSaver } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
const flush = () => new Promise(resolve => setImmediate(resolve));

function fixture(fetcher) {
  const elements = Object.fromEntries(['reader-conflict', 'reader-conflict-pending', 'reader-conflict-saved', 'reader-conflict-check']
    .map(id => [id, { textContent: '', hidden: true, disabled: false, addEventListener(_type, handler) { this.click = handler; } }]));
  const doc = { getElementById: id => elements[id] };
  const panel = setupProgressConflict({ doc, itemId: '42', getSlug: () => 'example',
    getChapters: () => [{ id: '1', label: '<Первая>' }, { id: '2', label: 'Вторая' }], fetcher });
  return { elements, panel, button: elements['reader-conflict-check'], pending: elements['reader-conflict-pending'], saved: elements['reader-conflict-saved'] };
}

test('compare displays pending and fetched values without writes or adopting a token', async () => {
  const requests = [];
  const f = fixture(async (...args) => {
    requests.push(args);
    return { ok: true, json: async () => ({ progress_save_allowed: true, progress_slug: 'example',
      progress_snapshot: 'not adopted', chapters: [{ id: '2', label: 'Вторая' }], progress: { cid: '2', page: 3 } }) };
  });
  f.panel.update({ cid: '1', page: 0 }); f.panel.show();
  assert.equal(f.elements['reader-conflict'].hidden, false);
  assert.equal(f.pending.textContent, 'Позиция этой вкладки (сохранение не подтверждено): <Первая> (ID 1), страница 1.');
  await f.button.click();
  assert.equal(f.saved.textContent, 'На момент проверки сохранено: Вторая (ID 2), страница 4.');
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
  result = { progress_save_allowed: true, progress_slug: 'example', progress: null };
  await f.button.click(); assert.match(f.saved.textContent, /сохранённой позиции.*нет/);
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
  resolve({ ok: true, json: async () => ({ progress_save_allowed: true, progress_slug: 'example', progress: null }) });
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
