import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';

const html = await readFile(new URL('../ui/index.html', import.meta.url), 'utf8');
const start = html.indexOf('let J=[],');
const end = html.indexOf('\nfunction drawBar()', start);
assert.ok(start >= 0 && end > start);
const code = html.slice(start, end);

function fixture() {
  const requests = [], events = [], renders = [];
  const badge = { classList: { toggle() {} } };
  const context = vm.createContext({
    api: () => new Promise((resolve, reject) => requests.push({ resolve, reject })),
    dispatchEvent: event => events.push(event.detail.map(job => job.status)),
    CustomEvent: class { constructor(_name, data) { this.detail = data.detail; } },
    $: () => badge, cur: 'downloads', drawJobs: () => renders.push('jobs'),
    drawBar: () => renders.push('bar'), pollExt: () => renders.push('ext'),
    lib: () => renders.push('library'), disk: () => renders.push('disk'),
  });
  vm.runInContext(code, context);
  return { context, requests, events, renders };
}
const one = status => [{ id: 1, status, speed: 0 }];

test('late old response cannot roll queue, summary or notifications backwards', async () => {
  const f = fixture();
  const first = f.context.poll(), second = f.context.poll();
  f.requests[1].resolve(one('готово')); await second;
  f.requests[0].resolve(one('в очереди')); await first;
  assert.deepEqual(f.events, [['готово']]);
  assert.deepEqual(f.renders, ['jobs', 'bar', 'ext']);
  assert.equal(vm.runInContext('J[0].status', f.context), 'готово');
});

test('slow responses can update while newer requests are pending; invalid or failed responses do not advance ordering', async () => {
  const f = fixture();
  const first = f.context.poll(), second = f.context.poll();
  f.requests[0].resolve(one('в очереди')); await first;
  assert.equal(f.events.length, 1);
  const third = f.context.poll(); f.requests[2].resolve({ error: 'unavailable' }); await third;
  f.requests[1].resolve(one('качается')); await second;
  assert.deepEqual(f.events, [['в очереди'], ['качается']]);
  const fourth = f.context.poll(); f.requests[3].reject(Error('offline'));
  await assert.rejects(fourth, /offline/);
  const fifth = f.context.poll(); f.requests[4].resolve(one('частично')); await fifth;
  assert.equal(vm.runInContext('J[0].status', f.context), 'частично');
});
