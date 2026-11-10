import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const source = await readFile(new URL('../ui/game-update-preview.js', import.meta.url), 'utf8');
const { compareCandidate } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);

test('comparison is explicit, safely renders paths and warns about incompleteness', async () => {
  const oldFetch = globalThis.fetch, oldDocument = globalThis.document;
  const button = { disabled: false }, status = { textContent: '' };
  const results = { children: [], replaceChildren() { this.children = []; }, append(x) { this.children.push(x); } };
  const requests = [];
  try {
    globalThis.document = { createElement: () => ({ children: [], append(child) { this.children.push(child); }, textContent: '' }) };
    globalThis.fetch = async (url, opts) => {
      assert.equal(button.disabled, true);
      requests.push({ url, headers: opts.headers, body: JSON.parse(opts.body) });
      return { ok: true, json: async () => ({ inspection: { save_comparison: {
        game_folder: 'C:/Game', incomplete: true,
        candidates: [{ path: '<img>.sav', relation: 'file_same_path' }, { path: 'saves', relation: 'directory_shared' }]
      } } }) };
    };
    assert.equal(requests.length, 0);
    await compareCandidate(7, { name: 'Game.zip', identity: 'abc' }, button, status, results);
    assert.deepEqual(requests[0].body, { id: 7, name: 'Game.zip', identity: 'abc', compare_saves: true });
    assert.equal(requests[0].headers['X-MH'], '1');
    assert.equal(results.children[0].children[0].textContent, '<img>.sav: совпадает путь файла в ZIP');
    assert.match(results.children[0].children[1].textContent, /содержимое не сравнивалось/);
    assert.match(status.textContent, /Поиск неполный/);
    assert.match(status.textContent, /обёртки/);
    assert.match(status.textContent, /CRC не проверены/);
    assert.match(status.textContent, /не план установки/);
    globalThis.fetch = async () => ({ ok: false, json: async () => ({ error: 'Архив изменился' }) });
    await compareCandidate(7, { name: 'Game.zip', identity: 'abc' }, button, status, results);
    assert.equal(status.textContent, 'Архив изменился');
    assert.equal(results.children.length, 0);
    assert.equal(button.disabled, false);
  } finally { globalThis.fetch = oldFetch; globalThis.document = oldDocument; }
});
