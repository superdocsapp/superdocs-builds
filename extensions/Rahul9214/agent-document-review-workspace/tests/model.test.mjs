import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const model = await import('../dist/model.js');
const fixtures = await import('../dist/fixtures.js');
const here = dirname(fileURLToPath(import.meta.url));

function byId(state, id) {
  return state.changes.find(c => c.id === id);
}

test('rejecting one change leaves other changes untouched', () => {
  const original = structuredClone(fixtures.initialState);
  const next = model.updateChangeStatus(original, 'chg-3', 'rejected');
  assert.equal(byId(next, 'chg-3').status, 'rejected');
  assert.equal(byId(next, 'chg-1').status, 'pending');
  assert.equal(byId(next, 'chg-2').status, 'pending');
});

test('approve one change and reject another; states remain independent', () => {
  let state = model.updateChangeStatus(structuredClone(fixtures.initialState), 'chg-1', 'approved');
  state = model.updateChangeStatus(state, 'chg-3', 'rejected');
  const approved = byId(state, 'chg-1');
  const rejected = byId(state, 'chg-3');
  const sibling = byId(state, 'chg-2');
  assert.equal(approved.status, 'approved');
  assert.equal(approved.artifactState, approved.after);
  assert.equal(rejected.status, 'rejected');
  assert.equal(rejected.artifactState, rejected.before);
  assert.equal(sibling.status, 'pending');
  assert.equal(sibling.artifactState, sibling.before);
  assert.equal(sibling.verification, 'verified');
  assert.equal(rejected.verification, 'mismatch');
});

test('revert one applied change without disturbing other approved changes', () => {
  let state = model.updateChangeStatus(structuredClone(fixtures.initialState), 'chg-1', 'applied');
  state = model.updateChangeStatus(state, 'chg-2', 'approved');
  const beforeRevert = {
    chg2: { ...byId(state, 'chg-2') },
    chg3: { ...byId(state, 'chg-3') },
    chg4: { ...byId(state, 'chg-4') }
  };
  const next = model.revertChange(state, 'chg-1');
  const reverted = byId(next, 'chg-1');
  assert.equal(reverted.status, 'reverted');
  assert.equal(reverted.artifactState, reverted.before);
  assert.notEqual(reverted.artifactState, reverted.after);
  assert.deepEqual(byId(next, 'chg-2'), beforeRevert.chg2);
  assert.deepEqual(byId(next, 'chg-3'), beforeRevert.chg3);
  assert.deepEqual(byId(next, 'chg-4'), beforeRevert.chg4);
  assert.equal(byId(next, 'chg-2').status, 'approved');
  assert.equal(byId(next, 'chg-2').artifactState, byId(next, 'chg-2').after);
});

test('revert is a no-op unless the change is approved or applied', () => {
  const original = structuredClone(fixtures.initialState);
  const pending = model.revertChange(original, 'chg-1');
  assert.equal(pending, original);
  const rejected = model.updateChangeStatus(structuredClone(fixtures.initialState), 'chg-3', 'rejected');
  const afterInvalidRevert = model.revertChange(rejected, 'chg-3');
  assert.equal(afterInvalidRevert, rejected);
  assert.equal(byId(afterInvalidRevert, 'chg-3').status, 'rejected');
  assert.equal(model.canRevert(byId(rejected, 'chg-3')), false);
  assert.equal(model.canRevert({ status: 'approved' }), true);
  assert.equal(model.canRevert({ status: 'applied' }), true);
});

test('reject cannot modify artifact content', () => {
  const original = structuredClone(fixtures.initialState);
  const artifactBefore = byId(original, 'chg-3').artifactState;
  const next = model.updateChangeStatus(original, 'chg-3', 'rejected');
  assert.equal(byId(next, 'chg-3').status, 'rejected');
  assert.equal(byId(next, 'chg-3').artifactState, artifactBefore);
  assert.equal(byId(next, 'chg-3').artifactState, byId(next, 'chg-3').before);
  assert.equal(byId(next, 'chg-1').artifactState, byId(original, 'chg-1').artifactState);
});

test('invalid status transitions are no-ops', () => {
  const original = structuredClone(fixtures.initialState);
  assert.equal(model.updateChangeStatus(original, 'chg-1', 'reverted'), original);
  assert.equal(model.updateChangeStatus(original, 'missing', 'approved'), original);

  const rejected = model.updateChangeStatus(structuredClone(fixtures.initialState), 'chg-3', 'rejected');
  assert.equal(model.updateChangeStatus(rejected, 'chg-3', 'approved'), rejected);
  assert.equal(model.updateChangeStatus(rejected, 'chg-3', 'applied'), rejected);

  const approved = model.updateChangeStatus(structuredClone(fixtures.initialState), 'chg-1', 'approved');
  assert.equal(model.updateChangeStatus(approved, 'chg-1', 'rejected'), approved);
  const reverted = model.revertChange(approved, 'chg-1');
  assert.equal(model.updateChangeStatus(reverted, 'chg-1', 'approved'), reverted);
});

test('review operations do not mutate fixture initial state so reset stays deterministic', () => {
  const snapshot = structuredClone(fixtures.initialState);
  let state = model.updateChangeStatus(structuredClone(fixtures.initialState), 'chg-1', 'approved');
  state = model.updateChangeStatus(state, 'chg-3', 'rejected');
  state = model.revertChange(state, 'chg-1');
  assert.notEqual(byId(state, 'chg-1').status, 'pending');
  assert.deepEqual(fixtures.initialState, snapshot);
  const reset = structuredClone(fixtures.initialState);
  assert.deepEqual(reset, snapshot);
  assert.equal(byId(reset, 'chg-1').status, 'pending');
  assert.equal(byId(reset, 'chg-1').artifactState, byId(reset, 'chg-1').before);
});

test('claim mismatches are explicit and countable', () => {
  const counts = model.summary(fixtures.initialState);
  assert.equal(counts.mismatch, 2);
  assert.equal(counts.verified, 2);
});

test('claimed-vs-actual mismatch remains explicit after review actions', () => {
  let state = model.updateChangeStatus(structuredClone(fixtures.initialState), 'chg-1', 'approved');
  state = model.updateChangeStatus(state, 'chg-3', 'rejected');
  state = model.revertChange(state, 'chg-1');
  const counts = model.summary(state);
  assert.equal(counts.mismatch, 2);
  assert.equal(counts.verified, 2);
  assert.equal(byId(state, 'chg-3').verification, 'mismatch');
  assert.equal(byId(state, 'chg-4').verification, 'mismatch');
  assert.equal(byId(state, 'chg-1').verification, 'verified');
  assert.match(byId(state, 'chg-3').claim, /No unrelated clauses/);
  assert.match(byId(state, 'chg-3').actual, /Payment terms changed/);
  assert.match(byId(state, 'chg-4').actual, /No corresponding document change/);
});

test('Cursor Agent and Claude Code pass through the same generic review model', () => {
  const src = readFileSync(join(here, '../src/model.ts'), 'utf8');
  assert.equal(src.includes('Cursor Agent'), false);
  assert.equal(src.includes('Claude Code'), false);
  assert.doesNotMatch(src, /\bagent\s*===|\bagent\s*==|\.agent\s*===|\.agent\s*==|switch\s*\(.*agent/);

  const cursor = fixtures.initialState.changes.find(c => c.agent === 'Cursor Agent');
  const claude = fixtures.initialState.changes.find(c => c.agent === 'Claude Code');
  assert.ok(cursor);
  assert.ok(claude);

  const approvedCursor = model.updateChangeStatus(structuredClone(fixtures.initialState), cursor.id, 'approved');
  const rejectedClaude = model.updateChangeStatus(structuredClone(fixtures.initialState), claude.id, 'rejected');
  assert.equal(byId(approvedCursor, cursor.id).status, 'approved');
  assert.equal(byId(approvedCursor, cursor.id).artifactState, cursor.after);
  assert.equal(byId(rejectedClaude, claude.id).status, 'rejected');
  assert.equal(byId(rejectedClaude, claude.id).artifactState, claude.before);
  assert.equal(byId(approvedCursor, claude.id).status, 'pending');
  assert.equal(byId(rejectedClaude, cursor.id).status, 'pending');

  const appliedClaude = model.updateChangeStatus(structuredClone(fixtures.initialState), claude.id, 'applied');
  const revertedClaude = model.revertChange(appliedClaude, claude.id);
  assert.equal(byId(revertedClaude, claude.id).status, 'reverted');
  assert.equal(byId(revertedClaude, claude.id).artifactState, claude.before);
});

test('evidence export preserves claimed versus actual', () => {
  const evidence = model.evidenceRecord(fixtures.initialState);
  const mismatch = evidence.decisions.find(c => c.id === 'chg-4');
  assert.equal(mismatch.verification, 'mismatch');
  assert.match(mismatch.claim, /Updated the current status/);
  assert.match(mismatch.actual, /No corresponding document change/);
});

test('exported evidence records reviewer decision, actual artifact state, and reverted state', () => {
  let state = model.updateChangeStatus(structuredClone(fixtures.initialState), 'chg-1', 'applied');
  state = model.updateChangeStatus(state, 'chg-2', 'approved');
  state = model.revertChange(state, 'chg-1');
  const evidence = model.evidenceRecord(state);
  const reverted = evidence.decisions.find(d => d.id === 'chg-1');
  const approved = evidence.decisions.find(d => d.id === 'chg-2');
  const pending = evidence.decisions.find(d => d.id === 'chg-3');
  assert.equal(reverted.reviewerDecision, 'reverted');
  assert.equal(reverted.status, 'reverted');
  assert.equal(reverted.artifactState, byId(state, 'chg-1').before);
  assert.equal(reverted.revertedState, byId(state, 'chg-1').before);
  assert.equal(approved.reviewerDecision, 'approved');
  assert.equal(approved.artifactState, byId(state, 'chg-2').after);
  assert.equal(approved.revertedState, null);
  assert.equal(pending.reviewerDecision, 'pending');
  assert.equal(pending.artifactState, byId(state, 'chg-3').before);
  assert.equal(pending.revertedState, null);
});
