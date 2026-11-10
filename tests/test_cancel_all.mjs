import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const source = await readFile(new URL('../ui/cancel-all.js', import.meta.url), 'utf8');
const { cancelSnapshot } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
const jobs = [
  { id: 1, status: 'качается' }, { id: 2, status: 'в очереди' },
  { id: 3, status: 'запланировано завтра' }, { id: 4, status: 'готово' },
];

test('declining confirmation never sends requests and reports the count', async () => {
  const sent = [];
  const result = await cancelSnapshot({ getJobs: async () => jobs, cancel: id => sent.push(id),
    confirm: message => { assert.match(message, /заданий: 3/); assert.match(message, /файлы могут остаться/); return false; } });
  assert.deepEqual(result, { status: 'declined', count: 3, failed: 0 });
  assert.deepEqual(sent, []);
});

test('confirms a snapshot, never cancels new or finished jobs and reports partial request failures', async () => {
  const sent = [];
  const copy = jobs.map(job => ({ ...job }));
  const result = await cancelSnapshot({ getJobs: async () => copy,
    confirm: () => { copy.push({ id: 5, status: 'в очереди' }); return true; },
    cancel: async id => { sent.push(id); if (id === 2) throw Error('offline'); } });
  assert.deepEqual(sent, [1, 2, 3]);
  assert.deepEqual(result, { status: 'requested', count: 3, failed: 1 });
});

test('empty list does not ask for confirmation and failed reads never cancel', async () => {
  assert.deepEqual(await cancelSnapshot({ getJobs: async () => [], confirm: () => assert.fail(), cancel: () => assert.fail() }),
    { status: 'empty', count: 0, failed: 0 });
  await assert.rejects(cancelSnapshot({ getJobs: async () => { throw Error('offline'); },
    confirm: () => assert.fail(), cancel: () => assert.fail() }));
});
