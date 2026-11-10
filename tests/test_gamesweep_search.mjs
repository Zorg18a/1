import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';

const source = await readFile(new URL('../legacy/gamesweep.py', import.meta.url), 'utf8');
const search = source.match(/<script id="searchlib">([\s\S]*?)<\/script>/)?.[1];
const rowText = source.match(/function rowText\(g, m\) \{[^\n]+\}/)?.[0];
const tabText = source.match(/const tabText = t => [^\n]+/)?.[0];
assert.ok(search && rowText && tabText);
const context = vm.createContext({});
vm.runInContext(`${search}\nconst dt = () => ''; const VL = {same:['есть']};\n${rowText}\n${tabText}\n` +
  `globalThis.check = (q, text, size) => accepts(parseQuery(q), text, size);` +
  `globalThis.row = rowText; globalThis.tab = tabText;`, context);

test('version rows and tabs find joined or spaced names in both directions', () => {
  const check = context.check;
  const version = context.row({ title: 'College Traits' },
    { name: 'College Traits v1.0.zip', path: 'C:/Games/College Traits v1.0.zip', version: 'v1.0', status: 'старая' });
  const tab = context.tab({ name: 'CollegeTraits', title: 'CollegeTraits [v1.1] [Dev]',
    host: 'f95zone.to', url: 'https://example.org/test', verdict: 'same', local: { name: 'CollegeTraits v1.0' } });
  assert.equal(check('CollegeTraits', version), true);
  assert.equal(check('College Traits', version), true);
  assert.equal(check('CollegeTraits', tab), true);
  assert.equal(check('College Traits', tab), true);
  assert.equal(check('CollegeTraits', 'College Traits 2'), true); // filtering is not identity matching
  assert.equal(check('CollegeTraits2', 'College Traits'), false);
  assert.equal(check('-CollegeTraits', version), false);
  assert.equal(check('CollegeTraits >1мб', version, 2 * 1048576), true);
  assert.equal(check('CollegeTraits >1мб', version, 10), false);
  assert.equal(check('CollegeTraits >1мб', tab, null), false);
});
