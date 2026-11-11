import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';

const source = await readFile(new URL('../ui/job-events.js', import.meta.url), 'utf8');
const { summarizeJobs, createQueueSummary, setupJobEvents } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
const jobs = ['качается', 'в очереди', 'запланировано завтра', 'готово', 'сохранено',
  'частично: 2 из 3', 'сохранено частично: достигнут лимит', 'ошибка: offline',
  'отменено', 'пропущено: уже скачано', 'неизвестно'].map(status => ({ status }));

test('counts partial saves separately from success and gives cautious guidance', () => {
  const text = summarizeJobs(jobs);
  for (const part of ['выполняется — 1', 'в очереди — 1', 'запланировано — 1',
    'готово/сохранено — 2', 'частично — 2', 'с ошибкой — 1', 'отменено — 1', 'пропущено — 1', 'другое — 1']) assert.ok(text.includes(part), part);
  assert.match(text, /проверьте очередь, библиотеку и оставшиеся файлы/);
  assert.doesNotMatch(summarizeJobs([{ status: 'готово' }]), /ручным повтором/);
  assert.equal(summarizeJobs(null), null); assert.equal(summarizeJobs([null]), null);
  assert.equal(summarizeJobs([{ status: 1 }]), null);
});

test('staleness does not pretend connection failed and invalid responses never refresh clock', () => {
  let time = 0; const state = createQueueSummary(() => time);
  assert.match(state.message(), /Получаем/);
  time = 10000; assert.match(state.message(), /состояние неизвестно/);
  assert.equal(state.record(jobs), true); assert.match(state.message(), /частично — 2/);
  time += 9999; assert.doesNotMatch(state.message(), /10 секунд/);
  assert.equal(state.record([{}]), false); time++;
  assert.match(state.message(), /могло устареть/);
  assert.match(state.message(), /фоновые вкладки/);
  assert.equal(state.record([]), true); assert.doesNotMatch(state.message(), /10 секунд/);
});

test('summary responds to queue events without making network requests', () => {
  const old = Object.fromEntries(['window', 'document', 'fetch'].map(k => [k, globalThis[k]]));
  const listeners = {}, inserted = [];
  try {
    globalThis.window = { addEventListener: (name, fn) => { listeners[name] = fn; }, setInterval: () => 1 };
    globalThis.document = { querySelector: () => ({ before: element => inserted.push(element) }),
      addEventListener() {}, createElement: () => ({ setAttribute(name, value) { this[name] = value; } }) };
    globalThis.fetch = () => assert.fail('unexpected fetch');
    setupJobEvents();
    const summary = inserted[1]; assert.equal(summary.role, 'status');
    listeners['mediahub:jobs']({ detail: jobs });
    assert.match(summary.textContent, /частично — 2/);
    listeners['mediahub:jobs']({ detail: {} }); assert.match(summary.textContent, /частично — 2/);
  } finally { for (const key of Object.keys(old)) { if (old[key] === undefined) delete globalThis[key]; else globalThis[key] = old[key]; } }
});

test('legacy rendering styles partially saved items as partial rather than success', async () => {
  const html = await readFile(new URL('../ui/index.html', import.meta.url), 'utf8');
  const code = html.slice(html.indexOf('function drawJobs()'), html.indexOf("$('clr').onclick"));
  assert.match(code, /function drawJobs/);
  const elements = { tsp: {}, jobs: {} };
  const context = { J: [], $: id => elements[id], isA: () => false, I: () => '', IC: {}, B: () => '', ETA: () => '', esc: value => String(value) };
  vm.createContext(context); vm.runInContext(code, context);
  const cases = [['сохранено частично: лимит', 'part'], ['частично: ошибка', 'part'],
    ['сохранено', 'ok'], ['готово', 'ok'], ['ошибка: сеть', 'err']];
  for (const [status, css] of cases) {
    context.J = [{ id: 1, title: 'test', status, pct: 100 }]; context.drawJobs();
    assert.match(elements.jobs.innerHTML, new RegExp(`class="js ${css}"`));
  }
});
