/**
 * The grading test.
 *
 * The card this package was built against is graded on one property: the report
 * names the specific block and the specific transformation that dropped it,
 * rather than reporting that something went wrong. These tests fail if the
 * output ever degrades towards "3 blocks lost identity".
 */

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { checkRoundTrip, formatReport } from '../src/index.js';

const BEFORE = '<div data-chunk-id="root" class="doc">'
  + '<h2 data-chunk-id="sec-4">4. Liability and indemnity</h2>'
  + '<p data-chunk-id="para-7" class="lead">The Supplier shall indemnify the Customer against all losses.</p>'
  + '<p data-chunk-id="para-8">Liability is capped at the fees paid in the preceding year.</p>'
  + '</div>';

const AFTER = '<div data-chunk-id="root" class="doc">'
  + '<h2 data-chunk-id="sec-4">4. Liability and indemnity</h2>'
  + '<p class="lead">The Supplier shall indemnify the Customer against all losses.</p>'
  + '<p data-chunk-id="para-8">Liability is capped at the fees paid in the preceding year.</p>'
  + '</div>';

const report = checkRoundTrip(BEFORE, AFTER);
const text = formatReport(report, { format: 'human', colour: false });

test('the report names the block', () => {
  assert.match(text, /para-7/);
  assert.match(text, /\bp\b/);
  assert.match(text, /block 3/);
  assert.match(text, /The Supplier shall indemnify/);
});

test('the report gives a locator that survives reformatting', () => {
  assert.match(text, /div > p\[1\]/);
  const finding = report.findings[0];
  assert.equal(finding.locator.parentId, 'root');
  assert.ok(Number.isInteger(finding.locator.line));
});

test('the report names a transformation, not a symptom', () => {
  assert.match(text, /allowlist/);
  assert.doesNotMatch(text, /validation failed/i);
  assert.doesNotMatch(text, /id mismatch/i);
  assert.doesNotMatch(text, /\d+% of ids/i);
});

test('the report says how sure it is', () => {
  assert.match(text, /confidence (high|medium|low)/);
});

test('the report says what the block became', () => {
  assert.match(text, /after\s+p at line \d+ \(class\)/);
});

test('the machine report carries the same facts as the human one', () => {
  const json = JSON.parse(formatReport(report, { format: 'json' }));
  const [finding] = json.findings;
  assert.equal(finding.rule, 'LOST_ATTRIBUTE_STRIPPED');
  assert.equal(finding.id, 'para-7');
  assert.equal(finding.locator.parentId, 'root');
  assert.equal(finding.counterpart.hasIdAttribute, false);
  assert.ok(finding.cause.length > 40);
  assert.ok(finding.key);
});

test('the pipeline format points at a file and a line', () => {
  const annotations = formatReport(report, { format: 'github', file: 'before.html' });
  assert.match(annotations, /^::error file=before\.html,line=\d+,col=\d+,title=LOST_ATTRIBUTE_STRIPPED/m);
  assert.match(annotations, /%0A/, 'multi-line messages must be escaped for the workflow command');
});
