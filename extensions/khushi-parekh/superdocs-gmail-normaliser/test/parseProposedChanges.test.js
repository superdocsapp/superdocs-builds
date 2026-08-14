/**
 * Runs without a live SuperDocs key and without any npm install:
 *   node --test
 * (Node 18+. Uses the built-in test runner, on purpose, so a stranger
 * can clone this repo and verify the claims with zero setup.)
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const { parseProposedChanges } = require('./parseProposedChanges');

test('parses a JSON-encoded string into an array (the documented gotcha)', () => {
  const raw = JSON.stringify([{ id: 'c1' }, { id: 'c2' }]);
  assert.deepEqual(parseProposedChanges(raw), [{ id: 'c1' }, { id: 'c2' }]);
});

test('passes through an already-parsed array unchanged', () => {
  const raw = [{ id: 'c1' }];
  assert.deepEqual(parseProposedChanges(raw), [{ id: 'c1' }]);
});

test('returns an empty array for null/undefined', () => {
  assert.deepEqual(parseProposedChanges(null), []);
  assert.deepEqual(parseProposedChanges(undefined), []);
});

test('returns an empty array for malformed JSON instead of throwing', () => {
  assert.deepEqual(parseProposedChanges('{not valid json'), []);
});

test('returns an empty array if the parsed JSON is not an array', () => {
  assert.deepEqual(parseProposedChanges(JSON.stringify({ id: 'c1' })), []);
});
