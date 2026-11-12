import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
const source = await readFile(new URL('../ui/game-check-resume.js', import.meta.url), 'utf8');
const { setupGameCheckResume } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
class Element {
  children = []; attrs = {}; handlers = {}; textContent = ''; disabled = false;
  append(...items) { this.children.push(...items); }
  replaceChildren(...items) { this.children = items; }
  setAttribute(key, value) { this.attrs[key] = value; }
  addEventListener(name, fn) { this.handlers[name] = fn; }
  click() { return this.handlers.click?.(); }
}
function setup(fetcher) {
  const anchor = new Element(); anchor.before = section => { anchor.section = section; };
  const doc = { querySelector: () => anchor, createElement: () => new Element() };
  const win = { addEventListener: (name, fn) => { win[name] = fn; }, setTimeout, clearTimeout, poll: () => { win.polled = true; } };
  setupGameCheckResume({ doc, win, fetcher });
  const [, , status, list] = anchor.section.children;
  const emit = jobs => win['mediahub:jobs']({ detail: jobs });
  return { win, status, list, emit };
}
const job = { id: 4, kind: 'gamecheck', status: 'отменено', game_check: { total: 86, ok: 2, pending: 83, unknown: 1, skipped: 0, errors: [{ id: 2, title: '<img>', reason: 'timeout' }], resume: true } };

test('explicit continuation sends only job id and reports real response', async () => {
  const calls = [];
  const f = setup(async (url, opts) => { calls.push([url, JSON.parse(opts.body), opts.headers]); return { ok: true, json: async () => ({ job: 5 }) }; });
  f.emit([job]); const row = f.list.children[0];
  f.emit([job]); assert.equal(f.list.children[0], row); // Unchanged polling preserves focus.
  assert.match(row.children[0].textContent, /всего 86|Всего 86/);
  assert.match(row.children[0].textContent, /неизвестно 1/);
  assert.match(row.children[1].textContent, /<img>.*timeout/);
  await row.children[2].click();
  assert.deepEqual(calls[0].slice(0, 2), ['/api/game/check', { resume: 4 }]);
  assert.equal(calls[0][2]['X-MH'], '1'); assert.match(f.status.textContent, /задание 5/);
  assert.equal(f.win.polled, true); assert.equal(row.children[2].disabled, true);
  f.emit([{ ...job, game_check: { ...job.game_check, resume: false } }]);
  assert.equal(f.list.children[0].children.length, 2);
});

test('failed request reports unknown; no retry before new jobs snapshot', async () => {
  let calls = 0;
  const f = setup(async () => { calls++; throw Error('offline'); });
  f.emit([job]); const button = f.list.children[0].children[2];
  await button.click(); await button.click();
  assert.equal(calls, 1); assert.match(f.status.textContent, /неизвестен/);
  f.emit([job]); await f.list.children[0].children[2].click(); assert.equal(calls, 2);
});

test('malformed snapshots never display a continuation button', () => {
  const f = setup(() => {});
  f.emit([{ ...job, game_check: { ...job.game_check, pending: '83' } }]);
  assert.equal(f.list.children.length, 0);
});
