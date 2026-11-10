import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
const source = await readFile(new URL('../ui/inbox-submit.js', import.meta.url), 'utf8');
const { makePlan, createInboxSubmit, createInboxHandler } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);

test('links-only converts every selected action except known and skip', () => {
  const actions = ['download', 'site', 'gamecard', 'track', 'link', 'known', 'skip', 'download'];
  const rows = actions.map((action, id) => ({ id, status: 'pending', action }));
  rows.push({ id: 99, status: 'done' });
  const plan = makePlan(rows, r => ({ on: r.id !== 7, action: r.action, kind: 'game' }), true);
  assert.deepEqual(plan.map(x => x.action), ['link', 'link', 'link', 'link', 'link', 'known', 'skip', 'skip']);
  assert.equal(makePlan(rows, r => ({ on: true, action: r.action, kind: 'game' }), false)[2].action, 'gamecard');
});

test('request validates responses, prevents in-flight duplicates and describes close opt-in', async () => {
  let resolve, count = 0, body;
  const submit = createInboxSubmit((_url, options) => {
    count++; body = JSON.parse(options.body);
    return new Promise(done => { resolve = done; });
  });
  const first = submit('a', false, [{ id: 2 }]);
  assert.equal((await submit('a', false, [])).status, 'busy');
  assert.equal(count, 1);
  resolve({ ok: true, json: async () => ({ download: 1, links: 2 }) });
  assert.match((await first).message, /не запрошено/);
  assert.equal(body.close, false);
  const second = submit('a', true, []);
  resolve({ ok: true, json: async () => ({ download: 0, links: 1 }) });
  assert.match((await second).message, /браузер может/);
});

test('HTTP, network, JSON and malformed results are unknown, never automatically retried', async () => {
  for (const response of [() => { throw Error('offline'); }, () => ({ ok: false }),
    () => ({ ok: true, json: () => { throw Error('bad json'); } }),
    () => ({ ok: true, json: () => ({ error: 'partial' }) }),
    () => ({ ok: true, json: () => ({ download: 0 }) }),
    () => ({ ok: true, json: () => ({ download: -1, links: 1 }) })]) {
    let calls = 0;
    const submit = createInboxSubmit(async () => { calls++; return response(); });
    const result = await submit('batch', true, []);
    assert.equal(result.status, 'unknown');
    assert.match(result.message, /Некоторые строки могли уже обработаться/);
    assert.equal(calls, 1);
  }
});

test('handler keeps result visible if refresh fails and unlocks', async () => {
  const sending = new Set(), messages = [];
  let release, redraws = 0, count = 0;
  const handler = createInboxHandler({ getBatch: () => ({ rows: [] }), getClose: () => false,
    state: () => {}, sending, redraw: () => { redraws++; }, status: m => messages.push(m),
    refresh: async () => { throw Error('offline'); }, submit: () => { count++; return new Promise(r => { release = r; }); } });
  const first = handler('a', true);
  await handler('a', true);
  assert.equal(count, 1);
  assert.equal(sending.has('a'), true);
  release({ status: 'success', message: 'OK' });
  await first;
  assert.equal(sending.has('a'), false);
  assert.match(messages.at(-1), /Ранее включённое отслеживание не отключается/);
  assert.equal(redraws, 2);
});
