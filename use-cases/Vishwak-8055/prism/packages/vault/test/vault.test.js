import { test } from 'node:test';
import assert from 'node:assert/strict';
import { Vault } from '../src/vault.js';

function paras(...texts) {
  return texts.map((text, index) => ({ index, text, styleId: null, runs: [{ text, bold: false, italic: false, underline: false }] }));
}

test('commit/undo/redo walk a linear timeline', () => {
  const v = new Vault();
  const v1 = v.commit(paras('A'));
  const v2 = v.commit(paras('A', 'B'));
  const v3 = v.commit(paras('A', 'B', 'C'));

  assert.equal(v.current().versionId, v3.versionId);
  assert.equal(v.undo().versionId, v2.versionId);
  assert.equal(v.undo().versionId, v1.versionId);
  assert.equal(v.canUndo(), false);
  assert.throws(() => v.undo(), /nothing to undo/);

  assert.equal(v.redo().versionId, v2.versionId);
  assert.equal(v.redo().versionId, v3.versionId);
  assert.equal(v.canRedo(), false);
  assert.throws(() => v.redo(), /nothing to redo/);
});

test('committing after an undo discards the redo-able future', () => {
  const v = new Vault();
  v.commit(paras('A'));
  v.commit(paras('A', 'B'));
  v.undo(); // back to 'A'
  const branch = v.commit(paras('A', 'X')); // new branch, discards 'A','B'

  assert.equal(v.current().versionId, branch.versionId);
  assert.equal(v.canRedo(), false, 'the discarded future must not be redo-able');
  // but it must still exist in the full graph for audit — never silently deleted
  const versionTexts = v.graph().map((g) => g.paragraphs.map((p) => p.text).join(','));
  assert.ok(versionTexts.includes('A,B'), 'discarded branch stays in the audit graph');
});

test('revertTo restores exact content and is itself a new, further-revertible commit', () => {
  const v = new Vault();
  const v1 = v.commit(paras('original'));
  const v2 = v.commit(paras('changed'));

  const reverted = v.revertTo(v1.versionId);
  assert.notEqual(reverted.versionId, v1.versionId, 'revert creates a NEW version, does not rewrite history');
  assert.equal(reverted.fingerprint, v1.fingerprint);
  assert.equal(reverted.kind, 'revert');
  assert.equal(v.current().paragraphs[0].text, 'original');

  // revert-of-a-revert: revert back to v2's content from here
  const revertOfRevert = v.revertTo(v2.versionId);
  assert.equal(revertOfRevert.fingerprint, v2.fingerprint);
  assert.equal(v.current().paragraphs[0].text, 'changed');
  assert.equal(v.graph().length, 4, 'v1, v2, revert-to-v1, revert-to-v2 all exist');
});

test('revertTo an unknown version id fails loudly, not silently', () => {
  const v = new Vault();
  v.commit(paras('A'));
  assert.throws(() => v.revertTo('not-a-real-id'), /unknown versionId/);
});

test('restore verification actually re-hashes rather than trusting the stored fingerprint', () => {
  const v = new Vault();
  const v1 = v.commit(paras('A'));
  v.commit(paras('B'));
  // Simulate corruption: mutate the stored paragraphs for v1 directly,
  // bypassing the public API, without updating its recorded fingerprint.
  const rawV1 = v.versions.get(v1.versionId);
  rawV1.paragraphs = paras('TAMPERED');

  assert.throws(() => v.undo(), /fingerprint mismatch/, 'undo must catch a fingerprint mismatch, not silently restore tampered content');
});
