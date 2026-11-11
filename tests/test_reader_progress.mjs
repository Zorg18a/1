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

test('dirty during debounce stays dirty when an older request completes', async () => {
  const sends = [], changes = [], statuses = [];
  const saver = createProgressSaver({ onDirty: d => changes.push(d), status: s => statuses.push(s),
    send: value => new Promise((resolve, reject) => sends.push({ value, resolve, reject })) });
  saver.submit({ page: 1 });
  saver.markDirty();
  sends[0].resolve(); await flush();
  assert.deepEqual(changes, [true]);
  assert.notEqual(statuses.at(-1), 'saved');
  saver.submit({ page: 2 });
  sends[1].resolve(); await flush();
  assert.deepEqual(changes, [true, false]);
  assert.equal(statuses.at(-1), 'saved');
});

test('failure and retry keep the warning until the newest position is confirmed', async () => {
  const sends = [], changes = [];
  const saver = createProgressSaver({ onDirty: d => changes.push(d), status: () => {},
    send: value => new Promise((resolve, reject) => sends.push({ value, resolve, reject })) });
  saver.submit({ page: 1 }); sends[0].reject(Error('offline')); await flush();
  saver.markDirty(); saver.submit({ page: 2 });
  saver.retry(); sends[1].resolve(); await flush();
  assert.deepEqual(changes, [true, false]);
  assert.deepEqual(sends.map(send => send.value.page), [1, 2]);
});

test('identity conflict stops retries and keeps unsaved warning', async () => {
  const calls = [], statuses = [], dirty = [];
  const saver = createProgressSaver({ onDirty: value => dirty.push(value), status: s => statuses.push(s),
    send: value => { calls.push(value); return Promise.reject(Object.assign(Error('changed'), { code: 'identity-conflict' })); } });
  saver.submit({ page: 1 }); await flush();
  assert.equal(statuses.at(-1), 'conflict');
  saver.submit({ page: 2 }); saver.retry(); await flush();
  assert.equal(calls.length, 1); assert.deepEqual(dirty, [true]);
  assert.equal(statuses.at(-1), 'conflict');
  await assert.rejects(sendProgress({}, async () => ({ status: 409, ok: false })), error => error.code === 'identity-conflict');
});
