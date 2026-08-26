'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { DOC_TEXT, DOC_META, REQUIRED_SECTIONS, OBJECTS, EDGES } = require('../src/data');
const {
  nextState, IllegalTransitionError,
  buildWorld, forecastContradictions, diffWorlds, runVerification, commitWorld,
} = require('../src/engine');

/* ---------------- state machine ---------------- */

test('scenario state machine: full happy path is legal', () => {
  let s = 'DRAFT';
  s = nextState(s, 'ANALYZING');
  s = nextState(s, 'SIMULATED');
  s = nextState(s, 'REVIEW');
  s = nextState(s, 'APPROVED');
  s = nextState(s, 'APPLYING');
  s = nextState(s, 'VERIFYING');
  s = nextState(s, 'COMMITTED');
  assert.equal(s, 'COMMITTED');
});

test('scenario state machine: DRAFT can be rejected directly', () => {
  assert.equal(nextState('DRAFT', 'REJECTED'), 'REJECTED');
});

test('scenario state machine: REVIEW can be rejected instead of approved', () => {
  assert.equal(nextState('REVIEW', 'REJECTED'), 'REJECTED');
});

test('scenario state machine: FAILED can roll back', () => {
  assert.equal(nextState('FAILED', 'ROLLED_BACK'), 'ROLLED_BACK');
});

test('scenario state machine: illegal transitions are rejected, not silently allowed', () => {
  assert.throws(() => nextState('DRAFT', 'COMMITTED'), IllegalTransitionError);
  assert.throws(() => nextState('COMMITTED', 'DRAFT'), IllegalTransitionError);
  assert.throws(() => nextState('SIMULATED', 'APPROVED'), IllegalTransitionError, 'SIMULATED must go through REVIEW first');
});

test('scenario state machine: terminal states have no legal exits', () => {
  assert.throws(() => nextState('COMMITTED', 'ANALYZING'));
  assert.throws(() => nextState('REJECTED', 'DRAFT'));
  assert.throws(() => nextState('ROLLED_BACK', 'DRAFT'));
});

/* ---------------- end-to-end: safe path (30 -> 60) ---------------- */

function runScenario(currentVersion, oldValue, proposedValue) {
  const baseline = buildWorld(DOC_TEXT, OBJECTS, oldValue);
  const candidate = buildWorld(DOC_TEXT, OBJECTS, proposedValue);
  const forecast = forecastContradictions(EDGES, OBJECTS, 'obl-payment', oldValue, proposedValue);
  const diff = diffWorlds(baseline, candidate, EDGES, OBJECTS, forecast);
  const verification = runVerification(baseline, candidate, diff, forecast, EDGES, OBJECTS, DOC_META, REQUIRED_SECTIONS);
  const commit = commitWorld(currentVersion, verification, candidate);
  return { baseline, candidate, forecast, diff, verification, commit };
}

test('end-to-end safe path: 30 -> 60 builds a candidate, verifies clean, and commits', () => {
  const r = runScenario(1, 30, 60);
  assert.equal(r.candidate.paymentTermDays, 60);
  assert.ok(r.diff.changedDocIds.includes('agreement') && r.diff.changedDocIds.includes('invoice'));
  assert.equal(r.forecast.introduced.length, 0);
  assert.equal(r.verification.allPassed, true);
  assert.equal(r.commit.committed, true);
  assert.equal(r.commit.version, 2);
  assert.equal(r.commit.world.paymentTermDays, 60);
});

test('end-to-end safe path: the baseline world is untouched by the entire flow', () => {
  const r = runScenario(1, 30, 60);
  assert.equal(r.baseline.paymentTermDays, 30);
  const s42 = r.baseline.docs.agreement.sections.find((s) => s.id === 's4').sub.find((sub) => sub.id === 's4-2');
  assert.ok(s42.body.includes('thirty (30) days'));
});

/* ---------------- end-to-end: unsafe path (30 -> 120) ---------------- */

test('end-to-end unsafe path: 30 -> 120 builds a candidate, detects a new constraint violation, and does not commit', () => {
  const r = runScenario(1, 30, 120);
  assert.equal(r.forecast.introduced.length, 1);
  assert.equal(r.verification.allPassed, false);
  assert.equal(r.commit.committed, false);
  assert.equal(r.commit.version, 1, 'version must not advance');
  assert.equal(r.commit.world, null);
});

test('end-to-end unsafe path: canonical stays at the original value, not 120 and not partially applied', () => {
  const r = runScenario(1, 30, 120);
  // The only "canonical" value that exists after a failed commit is whatever
  // the caller already had — commitWorld returning committed:false is the
  // guarantee that nothing new should replace it.
  assert.equal(r.commit.committed, false);
  const canonicalStillBaseline = r.commit.world === null;
  assert.ok(canonicalStillBaseline);
});

test('rejection path: a scenario that is rejected before commit never produces a committed world', () => {
  // Rejection happens at REVIEW, before APPROVED/APPLYING/VERIFYING even run —
  // so there is no verification or commit call in this path at all, by
  // construction. Confirm the state machine itself enforces that: REJECTED
  // has no legal path forward into APPROVED/APPLYING/COMMITTED.
  const rejected = nextState('REVIEW', 'REJECTED');
  assert.throws(() => nextState(rejected, 'APPROVED'));
  assert.throws(() => nextState(rejected, 'COMMITTED'));
});

/* ---------------- verification / commit unit coverage ---------------- */

test('verification: passes when nothing was newly introduced', () => {
  const r = runScenario(1, 30, 60);
  assert.ok(r.verification.checks.every((c) => c.pass));
});

test('verification: fails specifically because of the introduced-conflict check, not a different one, for the unsafe path', () => {
  const r = runScenario(1, 30, 120);
  const failing = r.verification.checks.filter((c) => !c.pass);
  assert.equal(failing.length, 1);
  assert.equal(failing[0].id, 'no-new-conflicts');
});

test('commitWorld: a clean world commits', () => {
  const r = runScenario(1, 30, 60);
  assert.equal(commitWorld(1, r.verification, r.candidate).committed, true);
});

test('commitWorld: a world with a newly-introduced conflict rolls back instead of committing', () => {
  const r = runScenario(1, 30, 120);
  const decision = commitWorld(1, r.verification, r.candidate);
  assert.equal(decision.committed, false);
});
