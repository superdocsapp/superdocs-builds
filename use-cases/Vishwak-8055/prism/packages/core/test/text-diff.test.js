import { test } from 'node:test';
import assert from 'node:assert/strict';
import { alignParagraphs, wordDiff } from '../src/diff/text-diff.js';

function para(index, text) {
  return { index, text, styleId: null, runs: [{ text, bold: false, italic: false, underline: false }] };
}

test('alignParagraphs marks identical paragraphs as common', () => {
  const base = { paragraphs: [para(0, 'Hello world.')] };
  const target = { paragraphs: [para(0, 'Hello world.')] };
  const ops = alignParagraphs(base, target);
  assert.equal(ops.length, 1);
  assert.equal(ops[0].type, 'common');
});

test('alignParagraphs pairs a 1:1 removed+added block as modified', () => {
  const base = { paragraphs: [para(0, 'The price is $50.')] };
  const target = { paragraphs: [para(0, 'The price is $75.')] };
  const ops = alignParagraphs(base, target);
  assert.equal(ops.length, 1);
  assert.equal(ops[0].type, 'modified');
  assert.equal(ops[0].base.text, 'The price is $50.');
  assert.equal(ops[0].target.text, 'The price is $75.');
});

test('alignParagraphs leaves an unmatched tail as pure added when longer than the removed block', () => {
  // 1 paragraph removed, 3 added at the same position: only the first pairs
  // as "modified"; the other 2 have no counterpart and must stay "added",
  // not silently disappear or get force-paired with nothing.
  const base = { paragraphs: [para(0, 'Old clause.')] };
  const target = {
    paragraphs: [para(0, 'New clause A.'), para(1, 'New clause B.'), para(2, 'New clause C.')],
  };
  const ops = alignParagraphs(base, target);
  const modified = ops.filter((o) => o.type === 'modified');
  const added = ops.filter((o) => o.type === 'added');
  assert.equal(modified.length, 1);
  assert.equal(added.length, 1);
  assert.equal(added[0].items.length, 2, 'the two extra paragraphs with no counterpart must surface as added, not vanish');
});

test('alignParagraphs handles a pure structural add with no removal at all', () => {
  const base = { paragraphs: [para(0, 'Section 1.')] };
  const target = { paragraphs: [para(0, 'Section 1.'), para(1, 'Section 2 (new).')] };
  const ops = alignParagraphs(base, target);
  assert.equal(ops.length, 2);
  assert.equal(ops[0].type, 'common');
  assert.equal(ops[1].type, 'added');
  assert.equal(ops[1].items.length, 1);
});

test('wordDiff is a real word-level diff, not a whole-string replace', () => {
  const parts = wordDiff('The cat sat on the mat.', 'The cat sat on the rug.');
  const removed = parts.filter((p) => p.removed).map((p) => p.value.trim());
  const added = parts.filter((p) => p.added).map((p) => p.value.trim());
  // The `diff` package's word tokenizer splits trailing punctuation into its
  // own token, so the shared "." is common to both sides, not part of the
  // changed span. Confirmed by running this, not assumed.
  assert.deepEqual(removed, ['mat']);
  assert.deepEqual(added, ['rug']);
});
