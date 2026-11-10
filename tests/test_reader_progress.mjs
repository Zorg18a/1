import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
const source = await readFile(new URL('../ui/reader-progress.js', import.meta.url), 'utf8');
const { createProgressSaver, sendProgress } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
const flush = () => new Promise(resolve => setImmediate(resolve));

test('writes are serialized and intermediate unsent positions are coalesced', async () => {
  const sends = [], statuses = [];
  const saver = createProgressSaver({ status: s => statuses.push(s), send: value => new Promise((resolve, reject) => sends.push({ value, resolve, reject })) });
  saver.submit({ page: 1 });
  saver.submit({ page: 2 }); saver.submit({ page: 3 });
  assert.equal(sends.length, 1);
  sends[0].resolve(); await flush();
  assert.equal(sends.length, 2);
  assert.deepEqual(sends[1].value, { page: 3 });
  assert.notEqual(statuses.at(-1), 'saved');
  sends[1].resolve(); await flush();
  assert.equal(statuses.at(-1), 'saved');
});

test('uncertain result pauses and retries latest position only on explicit request', async () => {
  const sends = [], statuses = [];
  const saver = createProgressSaver({ status: s => statuses.push(s), send: value => new Promise((resolve, reject) => sends.push({ value, resolve, reject })) });
  saver.submit({ page: 1 }); saver.submit({ page: 2 });
  sends[0].reject(Error('connection lost')); await flush();
  assert.equal(statuses.at(-1), 'unknown');
  saver.submit({ page: 3 }); await flush();
  assert.equal(sends.length, 1);
  saver.retry();
  assert.deepEqual(sends[1].value, { page: 3 });
  saver.retry(); assert.equal(sends.length, 2);
  sends[1].resolve(); await flush();
  assert.equal(statuses.at(-1), 'saved');
});

test('transport checks HTTP and JSON, retaining string item ids', async () => {
  let body;
  await sendProgress({ id: '9223372036854775807', cid: '12', page: 0 }, async (_url, options) => {
    body = JSON.parse(options.body);
    assert.equal(options.headers['X-MH'], '1');
    return { ok: true, json: async () => ({ ok: 1 }) };
  });
  assert.equal(body.id, '9223372036854775807');
  for (const response of [{ ok: false }, { ok: true, json: async () => ({ ok: 0 }) },
    { ok: true, json: async () => ({ error: 'missing' }) },
    { ok: true, json: async () => { throw Error('bad json'); } }]) {
    await assert.rejects(sendProgress({}, async () => response));
  }
  await assert.rejects(sendProgress({}, async () => { throw Error('offline'); }));
});
