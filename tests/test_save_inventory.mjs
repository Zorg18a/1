import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const source = await readFile(new URL('../ui/save-inventory.js', import.meta.url), 'utf8');
const { setupSaveInventory } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);

test('inventory is explicit, renders names as text and reports partial results', async () => {
  const old = Object.fromEntries(['window', 'document', 'fetch'].map(k => [k, globalThis[k]]));
  const handlers = {}, requests = [];
  const button = { disabled: false, addEventListener(_event, fn) { this.click = fn; } };
  const status = { textContent: '' };
  const results = { children: [], replaceChildren() { this.children = []; }, append(x) { this.children.push(x); } };
  const block = { querySelector: s => s === 'button' ? button : s === '[role="status"]' ? status : results };
  const section = { children: [], querySelector() { return this.children[0] || null; }, append(x) { this.children.push(x); } };
  try {
    globalThis.window = { addEventListener: (type, fn) => { handlers[type] = fn; } };
    globalThis.document = { querySelector: () => section, createElement: tag => tag === 'div' ? block :
      { children: [], append(child) { this.children.push(child); }, textContent: '' } };
    globalThis.fetch = async (url, options) => {
      assert.equal(button.disabled, true);
      requests.push({ url, headers: options.headers, body: JSON.parse(options.body) });
      return { ok: true, json: async () => ({ save_inventory: { game_folder: 'C:/Game', incomplete: true,
        total_bytes: '9007199254740993', files: [{ path: '<img>.sav', size_bytes: '9007199254740993' }] } }) };
    };
    setupSaveInventory();
    handlers['mediahub:game-panel']({ detail: { id: 7, g: { downloaded: true } } });
    handlers['mediahub:game-panel']({ detail: { id: 7, g: { downloaded: true } } });
    assert.equal(section.children.length, 1);
    assert.equal(requests.length, 0);
    await button.click();
    assert.deepEqual(requests[0].body, { id: 7, mode: 'save_inventory' });
    assert.equal(requests[0].headers['X-MH'], '1');
    assert.equal(results.children[0].children[0].textContent, '<img>.sav — 9007199254740993 Б');
    assert.match(status.textContent, /Просмотр неполный/);
    assert.match(status.textContent, /не резервная копия/);
    globalThis.fetch = async () => ({ ok: false, json: async () => ({ error: 'Нет доступа' }) });
    await button.click();
    assert.equal(status.textContent, 'Нет доступа');
    assert.equal(results.children.length, 0);
    assert.equal(button.disabled, false);
  } finally {
    for (const k of Object.keys(old)) { if (old[k] === undefined) delete globalThis[k]; else globalThis[k] = old[k]; }
  }
});
