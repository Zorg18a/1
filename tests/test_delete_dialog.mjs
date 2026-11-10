import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const source = await readFile(new URL('../ui/delete-dialog.js', import.meta.url), 'utf8');
const { deletionDescription, setupDeleteDialog } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);

test('explains actual target and file policy for files, folders, games and links', () => {
  assert.match(deletionDescription({ title: 'V', kind: 'video', path: 'C:\\V\\a.mp4' }), /без Корзины[\s\S]*C:\\V\\a.mp4/);
  assert.match(deletionDescription({ kind: 'site', path: 'x', root: 'C:\\Sites\\site' }), /папку целиком[\s\S]*C:\\Sites\\site/);
  assert.match(deletionDescription({ kind: 'game' }), /файлы останутся[\s\S]*Теги и заметки/);
  assert.match(deletionDescription({ kind: 'link' }), /только запись ссылки/);
  assert.match(deletionDescription({ kind: 'audio' }), /Путь к файлам не указан/);
});

test('cancel never sends, failures keep dialog open, and success uses confirmed snapshot', async () => {
  const old = Object.fromEntries(['window', 'document', 'fetch'].map(key => [key, globalThis[key]]));
  const elements = {};
  for (const id of ['delDlg', 'delT', 'delError', 'delC', 'delL', 'delF', 'v-games']) {
    elements[id] = { hidden: false, disabled: false, textContent: '', handlers: {},
      classList: { hidden: false, toggle(_name, value) { this.hidden = value; }, contains: () => true },
      addEventListener(type, fn) { this.handlers[type] = fn; } };
  }
  const dlg = elements.delDlg;
  dlg.showModal = () => { dlg.open = true; };
  dlg.close = () => { dlg.open = false; };
  let focused = false, requests = [], mode = 'failure', message = '';
  try {
    globalThis.document = { getElementById: id => elements[id], querySelector: () => ({ focus() { focused = true; } }) };
    globalThis.window = { lib: async () => {}, toast: text => { message = text; } };
    globalThis.fetch = async (url, options) => {
      requests.push({ url, data: JSON.parse(options.body) });
      if (mode === 'network') throw Error('offline');
      return mode === 'failure' ? { ok: false, json: async () => ({ error: 'Часть файлов могла быть удалена' }) } :
        { ok: true, json: async () => ({ ok: 1 }) };
    };
    setupDeleteDialog();
    const item = { id: 1, title: 'Video', kind: 'video', path: 'a.mp4', root: '' };
    window.MediaHubDelete.open(item);
    elements.delC.handlers.click();
    assert.equal(dlg.open, false); assert.equal(requests.length, 0);
    window.MediaHubDelete.open(item);
    item.path = 'changed-after-open.mp4';
    await elements.delF.handlers.click();
    assert.equal(dlg.open, true);
    assert.match(elements.delError.textContent, /Часть файлов/);
    assert.deepEqual(requests[0].data.expected, { title: 'Video', kind: 'video', path: 'a.mp4', root: '' });
    mode = 'network'; await elements.delL.handlers.click();
    assert.match(elements.delError.textContent, /результат неизвестен/);
    mode = 'success'; await elements.delL.handlers.click();
    assert.equal(dlg.open, false); assert.equal(focused, true);
    assert.equal(message, 'Убрано из библиотеки');
    window.MediaHubDelete.open({ id: 2, title: 'Game', kind: 'game', path: 'game' });
    assert.equal(elements.delF.classList.hidden, true);
  } finally {
    for (const [key, value] of Object.entries(old)) {
      if (value === undefined) delete globalThis[key]; else globalThis[key] = value;
    }
  }
});
