/**
 * The fixtures are the specification.
 *
 * Each pair is a failure an editor integration actually hits, and the expected
 * file is the exact report it produces. If a change to the diagnosis layer makes
 * a report vaguer, this is where it shows up.
 */

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { fixtureNames, runFixture } from './update-fixtures.js';

const names = fixtureNames();

test('there are fixtures to run', () => {
  assert.ok(names.length >= 10, `expected at least ten fixtures, found ${names.length}`);
});

for (const name of names) {
  test(`fixture ${name} reports exactly what it is pinned to`, () => {
    const { directory, text } = runFixture(name);
    const expected = readFileSync(join(directory, 'expected.txt'), 'utf8');
    assert.equal(text, expected, `run "npm run fixtures:update" and read the diff before committing`);
  });
}

test('the clean fixture is genuinely clean', () => {
  const { report } = runFixture('01-clean-round-trip');
  assert.deepEqual(report.findings, []);
  assert.equal(report.ok, true);
});

test('every fixture that should fail, fails', () => {
  const expectedFailures = names.filter(
    (name) => !['01-clean-round-trip', '07-legal-reorder', '09-out-of-flow-parts'].includes(name),
  );
  for (const name of expectedFailures) {
    const { report } = runFixture(name);
    assert.equal(report.ok, false, `${name} should have produced an error`);
  }
});

test('the fixtures that describe legal behaviour do not fail', () => {
  for (const name of ['01-clean-round-trip', '07-legal-reorder', '09-out-of-flow-parts']) {
    const { report } = runFixture(name);
    assert.equal(report.ok, true, `${name} should not have produced an error`);
  }
});
