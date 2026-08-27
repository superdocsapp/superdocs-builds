import { test } from 'node:test';
import assert from 'node:assert/strict';

import { checkRoundTrip } from '../src/index.js';
import { createBaseline, applyBaseline } from '../src/baseline.js';

const BEFORE = '<p data-chunk-id="a" class="lead">Known problem paragraph.</p>'
  + '<p data-chunk-id="b">Kept.</p>';
const AFTER = '<p class="lead">Known problem paragraph.</p><p data-chunk-id="b">Kept.</p>';

test('a baseline records only what would fail a build', () => {
  const report = checkRoundTrip(BEFORE, AFTER, { includeContentChanges: true });
  const baseline = createBaseline(report);
  assert.equal(baseline.accepted.length, 1);
  assert.equal(baseline.accepted[0].rule, 'LOST_ATTRIBUTE_STRIPPED');
  assert.equal(baseline.accepted[0].id, 'a');
  assert.ok(baseline.accepted[0].where);
});

test('applying a baseline clears the exit code but keeps the finding visible', () => {
  const report = checkRoundTrip(BEFORE, AFTER);
  const baselined = applyBaseline(report, createBaseline(report));
  assert.equal(baselined.ok, true);
  assert.equal(baselined.findings.length, 0);
  assert.equal(baselined.baselined.length, 1);
  assert.equal(baselined.baselined[0].baselined, true);
});

test('a baseline entry that no longer matches is counted as stale', () => {
  const report = checkRoundTrip(BEFORE, AFTER);
  const baseline = createBaseline(report);
  baseline.accepted.push({ key: 'LOST_BLOCK_REMOVED:00000000', rule: 'LOST_BLOCK_REMOVED', id: 'gone' });
  const baselined = applyBaseline(report, baseline);
  assert.equal(baselined.baselineApplied.matched, 1);
  assert.equal(baselined.baselineApplied.stale, 1);
});

test('an empty or absent baseline changes nothing', () => {
  const report = checkRoundTrip(BEFORE, AFTER);
  assert.equal(applyBaseline(report, null), report);
  assert.equal(applyBaseline(report, { accepted: [] }), report);
});

test('the finding key changes when the block or the cause changes', () => {
  const first = checkRoundTrip(BEFORE, AFTER).findings[0].key;
  const movedText = BEFORE.replace('Known problem paragraph.', 'A different paragraph entirely.');
  const movedAfter = AFTER.replace('Known problem paragraph.', 'A different paragraph entirely.');
  const second = checkRoundTrip(movedText, movedAfter).findings[0].key;
  assert.notEqual(first, second);
});

test('a baselined document is never described as clean', async () => {
  const { formatReport } = await import('../src/index.js');
  const report = checkRoundTrip(BEFORE, AFTER);
  const baselined = applyBaseline(report, createBaseline(report));
  const text = formatReport(baselined, { format: 'human', colour: false });
  assert.doesNotMatch(text, /clean: every identifier survived/);
  assert.match(text, /BASELINED/);
  assert.match(text, /no new findings/);
  assert.match(text, /baseline: 1 accepted, 1 still present here, 0 stale/);
});
