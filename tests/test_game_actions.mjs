import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';

const html = await readFile(new URL('../ui/index.html', import.meta.url), 'utf8');
const start = html.indexOf('function fillPanel(x)');
const end = html.indexOf('\nfunction openPanel(', start);
assert.ok(start >= 0 && end > start);
const code = html.slice(start, end);
const escapeCode = html.match(/^const esc=.*$/m)?.[0];
assert.ok(escapeCode);

function panel(overrides = {}) {
  const node = { innerHTML: '' };
  const game = { downloaded: true, update: true, version: '1', latest: '2',
    developer: '', thread: 'https://example.org/thread', links: [], genres: [],
    support: [], auto: true, desc: '', ...overrides };
  const context = { $: () => node, I: () => '', hue: () => 0, initials: () => 'X',
    B: () => '0', ago: () => '', GGEN: new Set() };
  vm.runInNewContext(`${escapeCode}\n${code}\nfillPanel(game)`,
    { ...context, game: { id: 1, title: 'Test', g: game } });
  return node.innerHTML;
}

test('update button explains whether it opens a thread or shows links', () => {
  const thread = panel();
  assert.match(thread, /data-ga="thread">Открыть страницу обновления/);
  assert.doesNotMatch(thread, /data-ga="thread">Обновить/);
  const links = panel({ thread: '', links: [{ host: 'site', url: 'https://example.org' }] });
  assert.match(links, /data-ga="links">Показать ссылки для обновления/);
  const notDownloaded = panel({ downloaded: false, update: false, thread: '', links: [{ host: 'site' }] });
  assert.match(notDownloaded, /data-ga="links">Показать ссылки для скачивания/);
  assert.doesNotMatch(notDownloaded, /data-ga="links">Скачать</);
  assert.doesNotMatch(panel({ update: false, thread: '' }), /страницу обновления/);
});

test('sort explanation is visible and linked to the select', () => {
  assert.match(html, /id="gso"[^>]*aria-describedby="gsort-hint"/);
  assert.match(html, /id="gsort-hint"[^>]*>Игры с найденными обновлениями всегда показаны первыми/);
});
