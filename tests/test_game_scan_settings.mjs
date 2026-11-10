import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
const source = await readFile(new URL('../ui/game-scan-settings.js', import.meta.url), 'utf8');
const { setupGameScanSettings } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
const flush = () => new Promise(resolve => setImmediate(resolve));

test('layout is loaded, validated, saved separately and errors are visible', async () => {
  const original = { document: globalThis.document, fetch: globalThis.fetch };
  const select = { disabled: true, value: '', addEventListener(_type, handler) { this.change = handler; } };
  const status = { textContent: '' };
  const row = { innerHTML: '', querySelector: key => key === 'select' ? select : status };
  const root = { after(element) { assert.equal(element, row); } };
  let fail = false, posted;
  try {
    globalThis.document = { querySelector: () => ({ closest: () => root }), createElement: () => row };
    globalThis.fetch = async (_url, options) => {
      if (!options) return { ok: true, json: async () => ({ games_layout: 'nested' }) };
      posted = JSON.parse(options.body);
      return fail ? { ok: false } : { ok: true, json: async () => posted };
    };
    setupGameScanSettings(); await flush();
    assert.equal(select.value, 'nested'); assert.equal(select.disabled, false);
    select.value = 'nested2'; await select.change();
    assert.deepEqual(posted, { games_layout: 'nested2' });
    assert.match(status.textContent, /пересканировать сейчас/);
    fail = true; select.value = 'flat'; await select.change();
    assert.equal(select.value, 'nested2'); assert.match(status.textContent, /Не удалось подтвердить/);
    assert.equal(select.disabled, false);
  } finally {
    globalThis.document = original.document; globalThis.fetch = original.fetch;
  }
});
