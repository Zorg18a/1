import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
const source = await readFile(new URL('../ui/reader-images.js', import.meta.url), 'utf8');
const { setupReaderImage } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);

function element() {
  return { children: [], events: {}, textContent: '', hidden: false,
    append(...args) { this.children.push(...args); }, setAttribute() {},
    addEventListener(name, fn) { this.events[name] = fn; }, focus() { this.focused = true; } };
}

test('retry retains the original identity and changes only the cache-buster', () => {
  const doc = { createElement: () => element() }, img = element();
  const identity = 'a'.repeat(64), src = `/mi/1/2/001.png?identity=${identity}`;
  const panel = setupReaderImage({ doc, image: img, number: 1, src });
  const [message, retry] = panel.children;
  img.events.error(); assert.match(message.textContent, /обновите читалку/);
  retry.events.click(); const first = img.src;
  assert.ok(first.startsWith(src + '&retry=')); assert.match(first, /&retry=[0-9]+-1$/);
  retry.events.click();
  assert.ok(img.src.startsWith(src + '&retry=')); assert.match(img.src, /&retry=[0-9]+-2$/);
  assert.notEqual(first, img.src);
});