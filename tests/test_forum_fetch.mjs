import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFile } from 'node:fs/promises';

for (const folder of ['extension', 'extension-firefox']) {
  test(`${folder}: topic waits for Pornolab post instead of just og:title`, async () => {
    const source = await readFile(new URL(`../${folder}/background.js`, import.meta.url), 'utf8');
    const code = source.slice(source.indexOf('async function fetchHtml(p)'), source.indexOf('async function handleTask(t)'));
    const calls = [], images = [
      '<meta property="og:title" content="loading">',
      '<h1 class="maintitle">Game</h1><div class="post_body"><img class="postImg"></div>',
    ];
    const context = vm.createContext({ URL,
      fetch: async (_url, options) => { calls.push(options.credentials); return { ok: true, text: async () => images[0] }; },
      ensureWindow: async () => { calls.push('window'); return { id: 1 }; },
      navigate: async () => calls.push('navigate'), sleep: async () => {},
      runInTab: async () => { calls.push('read'); return images.shift() || ''; },
      closeWnd: async () => calls.push('close'),
    });
    vm.runInContext(code + '\nglobalThis.readPage = fetchHtml;', context);
    const result = await context.readPage({ url: 'https://pornolab.net/forum/viewtopic.php?t=123' });
    assert.equal(result.via, 'window');
    assert.match(result.html, /post_body/);
    assert.deepEqual(calls, ['include', 'window', 'navigate', 'read', 'read', 'close']);
  });
}
