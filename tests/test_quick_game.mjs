import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const source = await readFile(new URL('../extension/quick-game.js', import.meta.url), 'utf8');
const firefox = await readFile(new URL('../extension-firefox/quick-game.js', import.meta.url), 'utf8');
const { isSupportedGameUrl, queueGame, setupQuickGame } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);

function browser(token) {
  const data = { token };
  return { data, storage: { local: {
    get: async () => ({ ...data }), set: async obj => Object.assign(data, obj),
    remove: async key => { delete data[key]; },
  } } };
}
const reply = (status, body) => ({ ok: status >= 200 && status < 300, status, json: async () => body });

test('both browser builds use identical one-click logic', () => assert.equal(source, firefox));

test('allow only HTTPS supported thread pages', () => {
  for (const url of ['https://f95zone.to/threads/game.123/', 'https://f95zone.to/threads/123/page-2#post',
    'https://pornolab.net/forum/viewtopic.php?t=3282477', 'https://pornolab.net/forum/viewtopic.php?t=2&start=20'])
    assert.equal(isSupportedGameUrl(url), true, url);
  for (const url of ['http://f95zone.to/threads/game.123/', 'https://evil.test/threads/game.123/',
    'https://f95zone.to.evil.test/threads/1', 'https://user@f95zone.to/threads/1',
    'https://f95zone.to:444/threads/1', 'https://f95zone.to/threads/',
    'https://f95zone.to/threads/x%2F123', 'https://f95zone.to/\nthreads/1',
    'https://pornolab.net.evil.test/forum/viewtopic.php?t=1', 'http://pornolab.net/forum/viewtopic.php?t=1',
    'https://pornolab.net/forum/viewtopic.php?t=1&t=2', 'https://pornolab.net/forum/viewtopic.php?t=abc',
    'https://pornolab.net/forum/index.php?t=1'])
    assert.equal(isSupportedGameUrl(url), false, url);
});

test('pending pairing does not enqueue or persist a retry', async () => {
  const ext = browser();
  const paths = [];
  const result = await queueGame(ext, async url => { paths.push(url); return reply(200, { status: 'pending' }); },
                                 'https://f95zone.to/threads/game.123/');
  assert.equal(result.error, 'pending');
  assert.equal(paths.length, 1);
  assert.ok(paths[0].endsWith('/ext/hello'));
  assert.equal(ext.data.token, undefined);
});

test('paired request uses the token and reports only queued status', async () => {
  const ext = browser('secret');
  const requests = [];
  const result = await queueGame(ext, async (url, options) => {
    requests.push({ url, options }); return reply(200, { job: 42, status: 'queued' });
  }, 'https://f95zone.to/threads/game.123/');
  assert.deepEqual(result, { ok: true, job: 42 });
  assert.equal(requests.length, 1);
  assert.equal(requests[0].options.headers['X-MH-Token'], 'secret');
  assert.equal(JSON.parse(requests[0].options.body).url, 'https://f95zone.to/threads/game.123/');
});

test('an approved extension receives and stores its token before queueing', async () => {
  const ext = browser();
  const paths = [];
  const result = await queueGame(ext, async url => {
    paths.push(url);
    return url.endsWith('/ext/hello') ? reply(200, { token: 'approved' }) : reply(200, { job: 3, status: 'queued' });
  }, 'https://f95zone.to/threads/game.123/');
  assert.deepEqual(result, { ok: true, job: 3 });
  assert.equal(ext.data.token, 'approved');
  assert.deepEqual(paths.map(url => new URL(url).pathname), ['/ext/hello', '/ext/game/add']);
});

test('popup action wakes the background and reports queued, not completed', async () => {
  const ext = browser('secret');
  ext.tabs = { query: async () => [{ url: 'https://f95zone.to/threads/game.123/' }] };
  const messages = [];
  ext.runtime = { sendMessage: async message => messages.push(message) };
  const button = { disabled: true, addEventListener: (_name, handler) => { button.click = handler; } };
  const message = { textContent: '' };
  const doc = { querySelector: selector => selector === '#quick-game' ? button : message };
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => reply(200, { status: 'queued', job: 4 });
  try {
    await setupQuickGame(ext, doc);
    assert.equal(button.disabled, false);
    await button.click();
    assert.deepEqual(messages, [{ type: 'wake' }]);
    assert.match(message.textContent, /очереди/);
    assert.equal(button.disabled, true);
  } finally { globalThis.fetch = originalFetch; }
});

test('revoked token and offline failures do not claim success', async () => {
  const ext = browser('stale');
  const url = 'https://f95zone.to/threads/game.123/';
  assert.equal((await queueGame(ext, async () => reply(401, {}), url)).error, 'auth');
  assert.equal(ext.data.token, undefined);
  assert.equal((await queueGame(ext, async () => { throw Error('offline'); }, url)).error, 'offline');
  assert.equal((await queueGame(ext, async () => { throw Error('should not be called'); }, 'https://evil.test/')).error, 'unsupported');
});
