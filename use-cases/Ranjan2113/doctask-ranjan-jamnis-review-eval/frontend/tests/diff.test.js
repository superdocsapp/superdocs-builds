/**
 * Diff tests. Run with `node --test frontend/tests/` -- no npm install, no
 * network, no API key. The diff is what reviewers actually read, so a bug here
 * changes the measurement rather than just the appearance.
 */

import test from 'node:test';
import assert from 'node:assert/strict';

import { diffHtml, diffTokens, isNoop, stripTags, tokenize } from '../src/diff.js';

/**
 * Concatenate the tokens of one op type.
 *
 * Note these come out without the whitespace that separated them in the
 * source: a space shared by both sides is an `equal` token, so it is not part
 * of the delete or insert runs. That is correct diff behaviour -- the shared
 * space genuinely did not change -- so the assertions below check for the
 * changed words rather than for a pretty-printed phrase.
 */
const textOf = (ops, type) =>
  ops
    .filter((op) => op.type === type)
    .map((op) => op.tokens.join(''))
    .join(' ')
    .replace(/\s+/g, ' ')
    .trim();

test('tokenize preserves whitespace so output rejoins exactly', () => {
  const input = 'thirty (30)  days';
  assert.equal(tokenize(input).join(''), input);
});

test('stripTags removes markup and normalises entities', () => {
  assert.equal(stripTags('<p>the &ldquo;Services&rdquo;</p>'), 'the "Services"');
  assert.equal(stripTags('<p data-chunk-id="abc">Hello</p>'), 'Hello');
});

test('identical text produces no insert or delete ops', () => {
  const ops = diffTokens(tokenize('same text'), tokenize('same text'));
  assert.ok(ops.every((op) => op.type === 'equal'));
});

test('a changed number shows as a delete plus an insert', () => {
  const ops = diffHtml(
    '<p>pay within thirty (30) days of receipt</p>',
    '<p>pay within ninety (90) days of receipt</p>'
  );
  assert.equal(textOf(ops, 'delete'), 'thirty (30)');
  assert.equal(textOf(ops, 'insert'), 'ninety (90)');
  assert.ok(textOf(ops, 'equal').includes('days of receipt'));
  assert.ok(
    !textOf(ops, 'equal').includes('thirty'),
    'the changed number must not also appear as unchanged'
  );
});

test('a deleted clause shows as delete only', () => {
  const ops = diffHtml('<p>The liability cap applies.</p>', null);
  assert.equal(textOf(ops, 'insert'), '');
  assert.ok(textOf(ops, 'delete').includes('liability cap'));
});

test('the termination flip is visible as a party swap', () => {
  const ops = diffHtml(
    '<p>Either party may terminate this Agreement for convenience</p>',
    '<p>The Vendor may terminate this Agreement for convenience</p>'
  );
  assert.equal(textOf(ops, 'delete'), 'Either party');
  assert.equal(textOf(ops, 'insert'), 'The Vendor');
});

test('rejoining equal+delete reconstructs the old side exactly', () => {
  const oldText = 'The Client shall pay within thirty (30) days.';
  const newText = 'The Client shall pay within ninety (90) days.';
  const ops = diffTokens(tokenize(oldText), tokenize(newText));

  const rebuiltOld = ops
    .filter((op) => op.type !== 'insert')
    .map((op) => op.tokens.join(''))
    .join('');
  const rebuiltNew = ops
    .filter((op) => op.type !== 'delete')
    .map((op) => op.tokens.join(''))
    .join('');

  assert.equal(rebuiltOld, oldText, 'diff must not lose or invent old text');
  assert.equal(rebuiltNew, newText, 'diff must not lose or invent new text');
});

test('isNoop matches the backend rule', () => {
  assert.ok(isNoop('<p>Same  text</p>', '<p>Same text</p>'));
  assert.ok(!isNoop('<p>A</p>', '<p>B</p>'));
});

test('empty and null inputs do not throw', () => {
  assert.deepEqual(diffHtml(null, null), []);
  assert.equal(tokenize('').length, 0);
});
