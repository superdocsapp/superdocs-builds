/**
 * The drop-in replacement for the round-trip check in the SuperDocs editor
 * integration guide.
 *
 * The guide's version is three lines and answers yes or no:
 *
 *   const inIds  = [...incoming.matchAll(/data-chunk-id="([^"]+)"/g)].map(m => m[1]);
 *   const outIds = [...roundTripped.matchAll(/data-chunk-id="([^"]+)"/g)].map(m => m[1]);
 *   console.assert(inIds.every(id => outIds.includes(id)), "Chunk IDs did not survive");
 *
 * That assert tells you a round trip failed. This one tells you which block, at
 * which line, and which transformation dropped it -- and it does not fire on a
 * legal reorder, an out-of-flow part your editor does not render, or a
 * serialiser that re-encoded an entity.
 *
 * Copy this file into your editor's test suite, replace `roundTripThroughEditor`
 * with your own setHtml/getHtml pair, and run it against every block type your
 * product uses: headings, paragraphs, lists, list items, blockquotes, code
 * blocks, horizontal rules, tables. A gap in any single type surfaces in
 * production as occasional silent edit failures.
 */

import { test } from 'node:test';

import { assertRoundTrip } from '../src/index.js';
// In your own repository:
// import { assertRoundTrip } from 'superdocs-block-identity-guard';

/** Stand-in for your editor. Replace with the real thing. */
function roundTripThroughEditor(html) {
  // editor.setHtml(html);
  // return editor.getHtml();
  return html;
}

const BLOCK_TYPES = {
  heading: '<h1 data-chunk-id="h-1">Master Services Agreement</h1>',
  paragraph: '<p data-chunk-id="p-1">The Supplier shall indemnify the Customer.</p>',
  list: '<ul data-chunk-id="ul-1"><li data-chunk-id="li-1">Direct losses</li>'
    + '<li data-chunk-id="li-2">Indirect losses</li></ul>',
  blockquote: '<blockquote data-chunk-id="q-1">As set out in Schedule 1.</blockquote>',
  codeBlock: '<pre data-chunk-id="pre-1"><code>npm run check</code></pre>',
  horizontalRule: '<p data-chunk-id="p-2">Above</p><hr data-chunk-id="hr-1"><p data-chunk-id="p-3">Below</p>',
  table: '<table data-chunk-id="t-1"><tr data-chunk-id="tr-1">'
    + '<td data-chunk-id="td-1">Implementation</td><td data-chunk-id="td-2">1200</td></tr></table>',
  diagram: '<figure data-chunk-id="fig-1" data-diagram-type="mermaid" data-diagram-source="graph TD; A-->B;">'
    + '<svg></svg></figure>',
  outOfFlowPart: '<p data-chunk-id="ft-1" data-part-type="footer">Page 1 of 12</p>'
    + '<p data-chunk-id="p-4">Body text.</p>',
};

for (const [name, html] of Object.entries(BLOCK_TYPES)) {
  test(`${name} survives the editor round trip`, () => {
    // Throws with the full report, so a failing test says what to fix.
    assertRoundTrip(html, roundTripThroughEditor(html));
  });
}

test('the whole document survives at once', () => {
  const document = `<div data-chunk-id="root">${Object.values(BLOCK_TYPES).join('')}</div>`;
  assertRoundTrip(document, roundTripThroughEditor(document));
});

/**
 * If your editor genuinely cannot render headers and footers, tell the guard so
 * rather than deleting the assertion: an omitted out-of-flow part is a note by
 * default, and only `strictParts` makes it a failure.
 */
test('an editor with no footer affordance still passes', () => {
  const before = '<p data-chunk-id="ft-1" data-part-type="footer">Page 1 of 12</p>'
    + '<p data-chunk-id="p-1">Body text.</p>';
  const after = '<p data-chunk-id="p-1">Body text.</p>';
  assertRoundTrip(before, after);
});
