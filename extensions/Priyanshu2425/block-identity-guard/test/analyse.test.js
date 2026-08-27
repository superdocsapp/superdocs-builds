import { test } from 'node:test';
import assert from 'node:assert/strict';

import { checkRoundTrip, assertRoundTrip, RoundTripError } from '../src/index.js';
import { longestIncreasingSubsequence } from '../src/analyse.js';

const rules = (report) => report.findings.map((finding) => finding.rule);
const findingFor = (report, rule) => report.findings.find((finding) => finding.rule === rule);

test('an identical round trip reports nothing', () => {
  const html = '<p data-chunk-id="a">One</p><p data-chunk-id="b">Two</p>';
  const report = checkRoundTrip(html, html);
  assert.equal(report.ok, true);
  assert.deepEqual(report.findings, []);
  assert.equal(report.counts.intact, 2);
});

test('serialisation noise is not a finding', () => {
  const before = '<p data-chunk-id="a" class="lead">clause 3 &amp; 4</p>\n<p data-chunk-id="b">Two</p>';
  const after = '<p class="lead" data-chunk-id="a">clause&nbsp;3 &#38; 4</p><p data-chunk-id="b">   Two   </p>';
  const report = checkRoundTrip(before, after);
  assert.deepEqual(report.findings, []);
});

test('a stripped identifier names the allowlist, the block and its text', () => {
  const before = '<p data-chunk-id="a" class="lead">The Supplier shall indemnify the Customer.</p>'
    + '<p data-chunk-id="b">Liability is capped at the fees paid.</p>';
  const after = '<p class="lead">The Supplier shall indemnify the Customer.</p>'
    + '<p data-chunk-id="b">Liability is capped at the fees paid.</p>';
  const report = checkRoundTrip(before, after);
  const finding = findingFor(report, 'LOST_ATTRIBUTE_STRIPPED');
  assert.ok(finding, 'expected LOST_ATTRIBUTE_STRIPPED');
  assert.equal(finding.id, 'a');
  assert.equal(finding.locator.tag, 'p');
  assert.match(finding.cause, /allowlist/);
  assert.equal(finding.confidence, 'high');
  assert.ok(finding.counterpart.attributes.includes('class'));
  assert.equal(report.ok, false);
});

test('a tag change is reported as a rebuild, not a strip', () => {
  const before = '<h2 data-chunk-id="a">4. Liability and indemnity</h2><p data-chunk-id="b">Body text.</p>';
  const after = '<div class="heading-2">4. Liability and indemnity</div><p data-chunk-id="b">Body text.</p>';
  const finding = findingFor(checkRoundTrip(before, after), 'LOST_NODE_REBUILT');
  assert.ok(finding);
  assert.match(finding.cause, /from h2 to div/);
});

test('a block that is simply gone is not blamed on a sanitiser', () => {
  const before = '<p data-chunk-id="a">Kept</p><p data-chunk-id="b">Removed entirely from the document</p>';
  const after = '<p data-chunk-id="a">Kept</p>';
  const finding = findingFor(checkRoundTrip(before, after), 'LOST_BLOCK_REMOVED');
  assert.ok(finding);
  assert.equal(finding.id, 'b');
});

test('an identifier on two blocks is reported as ambiguous, with both blocks named', () => {
  const before = '<p data-chunk-id="a">First half of the clause.</p>';
  const after = '<p data-chunk-id="a">First half</p><p data-chunk-id="a">of the clause.</p>';
  const finding = findingFor(checkRoundTrip(before, after), 'DUPLICATE_ID');
  assert.ok(finding);
  assert.equal(finding.members.length, 2);
  assert.match(finding.cause, /ambiguous/);
});

test('a duplicate already present in the input is a warning about the input', () => {
  const html = '<p data-chunk-id="a">One</p><p data-chunk-id="a">Two</p>';
  const report = checkRoundTrip(html, html);
  assert.ok(rules(report).includes('DUPLICATE_ID_IN_SOURCE'));
  assert.equal(findingFor(report, 'DUPLICATE_ID_IN_SOURCE').severity, 'warning');
});

test('wholesale regeneration is one finding, not one per block', () => {
  const before = '<p data-chunk-id="a">One</p><p data-chunk-id="b">Two</p><p data-chunk-id="c">Three</p>';
  const after = '<p data-chunk-id="x">One</p><p data-chunk-id="y">Two</p><p data-chunk-id="z">Three</p>';
  const report = checkRoundTrip(before, after);
  assert.deepEqual(rules(report), ['IDS_REGENERATED']);
  assert.match(findingFor(report, 'IDS_REGENERATED').cause, /editor set its own content/);
});

test('a document stripped of every identifier says so once', () => {
  const before = '<p data-chunk-id="a">One</p><p data-chunk-id="b">Two</p>';
  const after = '<p>One</p><p>Two</p>';
  const report = checkRoundTrip(before, after);
  assert.deepEqual(rules(report), ['ALL_IDS_STRIPPED']);
});

test('a markdown hop is distinguished from an attribute allowlist', () => {
  const before = '<div data-chunk-id="root" class="doc">'
    + '<h2 data-chunk-id="a">Escalation</h2>'
    + '<p data-chunk-id="b"><span class="term">Tickets</span> escalate to the account manager.</p>'
    + '<p data-chunk-id="c">Then to the steering group.</p>'
    + '<p data-chunk-id="d">Timings are in Schedule 4.</p></div>';
  const after = '<div data-chunk-id="root" class="doc">'
    + '<h2>Escalation</h2>'
    + '<p>Tickets escalate to the account manager.</p>'
    + '<p>Then to the steering group.</p>'
    + '<p>Timings are in Schedule 4.</p></div>';
  const report = checkRoundTrip(before, after);
  const group = findingFor(report, 'LOST_SUBTREE');
  assert.ok(group, 'four losses under one surviving ancestor should group');
  assert.equal(group.id, 'root');
  assert.match(group.cause, /LOST_MARKDOWN_HOP/);
  assert.equal(group.members.length, 4);
});

test('losses under one ancestor collapse into a single finding that still names each block', () => {
  const before = '<table data-chunk-id="t"><tr data-chunk-id="r1"><td data-chunk-id="c1">Service</td>'
    + '<td data-chunk-id="c2">Rate</td></tr><tr data-chunk-id="r2"><td data-chunk-id="c3">Implementation</td>'
    + '<td data-chunk-id="c4">1200</td></tr></table>';
  const after = '<table data-chunk-id="t"><tr><td>Service</td><td>Rate</td></tr>'
    + '<tr><td>Implementation</td><td>1200</td></tr></table>';
  const group = findingFor(checkRoundTrip(before, after), 'LOST_SUBTREE');
  assert.ok(group);
  assert.equal(group.id, 't');
  assert.equal(group.members.length, 6);
  assert.deepEqual(group.members.map((member) => member.id).sort(), ['c1', 'c2', 'c3', 'c4', 'r1', 'r2']);
});

test('a reorder is reported, and does not fail the check', () => {
  const before = '<p data-chunk-id="a">One</p><p data-chunk-id="b">Two</p><p data-chunk-id="c">Three</p>';
  const after = '<p data-chunk-id="b">Two</p><p data-chunk-id="a">One</p><p data-chunk-id="c">Three</p>';
  const report = checkRoundTrip(before, after);
  assert.equal(report.ok, true);
  assert.deepEqual(rules(report), ['BLOCK_MOVED']);
});

test('a deletion does not report every block after it as moved', () => {
  const before = ['a', 'b', 'c', 'd', 'e']
    .map((id) => `<p data-chunk-id="${id}">Paragraph ${id}</p>`).join('');
  const after = ['a', 'c', 'd', 'e']
    .map((id) => `<p data-chunk-id="${id}">Paragraph ${id}</p>`).join('');
  const report = checkRoundTrip(before, after);
  assert.equal(report.counts.moved, 0, 'shifting is not moving');
  assert.deepEqual(rules(report), ['LOST_BLOCK_REMOVED']);
});

test('an out-of-flow part missing from the editor view is a note, not a failure', () => {
  const before = '<p data-chunk-id="a">Body</p><p data-chunk-id="f" data-part-type="footer">Page 1 of 12</p>';
  const after = '<p data-chunk-id="a">Body</p>';
  const report = checkRoundTrip(before, after);
  assert.equal(report.ok, true);
  assert.deepEqual(rules(report), ['PART_OMITTED']);
  assert.match(findingFor(report, 'PART_OMITTED').cause, /deleted_part_chunk_ids/);
});

test('strictParts turns an omitted part into a failure for integrations that own parts', () => {
  const before = '<p data-chunk-id="a">Body</p><p data-chunk-id="f" data-part-type="footer">Page 1 of 12</p>';
  const after = '<p data-chunk-id="a">Body</p>';
  const report = checkRoundTrip(before, after, { strictParts: true });
  assert.equal(report.ok, false);
  assert.equal(findingFor(report, 'PART_OMITTED').severity, 'error');
});

test('an out-of-flow part that is present but stripped is a real loss', () => {
  const before = '<p data-chunk-id="a">Body</p><p data-chunk-id="f" data-part-type="footer">Page 1 of 12</p>';
  const after = '<p data-chunk-id="a">Body</p><p data-part-type="footer">Page 1 of 12</p>';
  const report = checkRoundTrip(before, after);
  assert.equal(report.ok, false);
  assert.ok(rules(report).includes('LOST_ATTRIBUTE_STRIPPED'));
});

test('a surviving block that lost its diagram source is an error with the consequence named', () => {
  const before = '<figure data-chunk-id="d" data-diagram-type="mermaid" data-diagram-source="graph TD; A-->B;">'
    + '<svg></svg></figure>';
  const after = '<figure data-chunk-id="d"><svg></svg></figure>';
  const report = checkRoundTrip(before, after);
  const finding = findingFor(report, 'DATA_ATTRIBUTE_DROPPED');
  assert.ok(finding);
  assert.equal(finding.severity, 'error');
  assert.ok(finding.evidence.some((item) => item.includes('data-diagram-source')));
});

test('an unknown data attribute going missing is a warning, not an error', () => {
  const before = '<p data-chunk-id="a" data-house-style="tight">Body</p>';
  const after = '<p data-chunk-id="a">Body</p>';
  const finding = findingFor(checkRoundTrip(before, after), 'DATA_ATTRIBUTE_DROPPED');
  assert.equal(finding.severity, 'warning');
  assert.equal(checkRoundTrip(before, after).ok, true);
});

test('editor bookkeeping attributes are not treated as document meaning', () => {
  const before = '<p data-chunk-id="a" data-slate-node="element">Body</p>';
  const after = '<p data-chunk-id="a">Body</p>';
  assert.deepEqual(checkRoundTrip(before, after).findings, []);
});

test('new identifiers are reported, and a majority of them is called out', () => {
  const before = '<p data-chunk-id="a">One</p>';
  const after = '<p data-chunk-id="a">One</p><p data-chunk-id="n1">Typed</p><p data-chunk-id="n2">More</p>';
  const finding = findingFor(checkRoundTrip(before, after), 'NEW_IDS');
  assert.ok(finding);
  assert.match(finding.cause, /minting its own identifiers/);
});

test('text edits are silent by default and reportable on request', () => {
  const before = '<p data-chunk-id="a">The Supplier shall indemnify the Customer.</p>';
  const after = '<p data-chunk-id="a">The Supplier shall indemnify the Customer in full.</p>';
  assert.deepEqual(checkRoundTrip(before, after).findings, []);
  const verbose = checkRoundTrip(before, after, { includeContentChanges: true });
  assert.deepEqual(rules(verbose), ['CONTENT_CHANGED']);
  assert.equal(verbose.ok, true);
});

test('a before document with no identifiers says so, and suggests the attribute it found', () => {
  const report = checkRoundTrip('<p data-block-id="a">One</p>', '<p>One</p>');
  const finding = findingFor(report, 'NO_IDS_IN_SOURCE');
  assert.ok(finding);
  assert.ok(finding.evidence.some((item) => item.includes('data-block-id')));
});

test('a custom identifier attribute is honoured', () => {
  const before = '<p data-block-id="a">One</p>';
  const after = '<p>One</p>';
  const report = checkRoundTrip(before, after, { idAttribute: 'data-block-id' });
  assert.deepEqual(rules(report), ['ALL_IDS_STRIPPED']);
});

test('findings carry a stable key across runs', () => {
  const before = '<p data-chunk-id="a" class="lead">The Supplier shall indemnify.</p>'
    + '<p data-chunk-id="b">Kept.</p>';
  const after = '<p class="lead">The Supplier shall indemnify.</p><p data-chunk-id="b">Kept.</p>';
  const first = checkRoundTrip(before, after).findings[0].key;
  const second = checkRoundTrip(before, after).findings[0].key;
  assert.equal(first, second);
  assert.match(first, /^LOST_ATTRIBUTE_STRIPPED:[0-9a-f]{8}$/);
});

test('assertRoundTrip throws with the report attached, and passes on a clean trip', () => {
  const html = '<p data-chunk-id="a">One</p>';
  assert.equal(assertRoundTrip(html, html).ok, true);
  assert.throws(
    () => assertRoundTrip(html, '<p>One</p>'),
    (error) => error instanceof RoundTripError && error.report.findings.length === 1,
  );
});

test('bad input fails loudly rather than reporting a clean document', () => {
  assert.throws(() => checkRoundTrip(null, '<p></p>'), TypeError);
  assert.throws(() => checkRoundTrip('<p></p>', undefined), TypeError);
  assert.throws(() => checkRoundTrip('x'.repeat(50), '<p></p>', { maxBytes: 10 }), RangeError);
});

test('longest increasing subsequence finds the run that did not move', () => {
  assert.deepEqual(longestIncreasingSubsequence([1, 2, 3]), [0, 1, 2]);
  assert.deepEqual(longestIncreasingSubsequence([3, 1, 2]), [1, 2]);
  assert.deepEqual(longestIncreasingSubsequence([]), []);
  assert.deepEqual(longestIncreasingSubsequence([5]), [0]);
});

test('a document with thousands of blocks stays readable and finishes', () => {
  const size = 2000;
  const blocks = [];
  for (let i = 0; i < size; i += 1) {
    blocks.push(`<p data-chunk-id="id-${i}" class="c">Clause ${i} on liability and indemnity.</p>`);
  }
  const before = `<div data-chunk-id="root">${blocks.join('')}</div>`;
  const after = before.replace(/ data-chunk-id="id-(1|2|3|4|5)"/g, '');

  const started = Date.now();
  const report = checkRoundTrip(before, after);
  assert.ok(Date.now() - started < 10000, 'a 2,000 block document should not take ten seconds');
  assert.equal(report.counts.beforeBlocks, size + 1);
  assert.equal(report.counts.lost, 5);
  assert.deepEqual(rules(report), ['LOST_SUBTREE'], 'five losses under one ancestor are one finding');
  assert.equal(report.findings[0].members.length, 5, 'and the finding still names all five');
});
