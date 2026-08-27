# Block identity guard

A round-trip check for SuperDocs documents. Give it the HTML SuperDocs sent and
the HTML your integration sent back, and it tells you **which blocks lost their
`data-chunk-id`, where they are, and what dropped them**.

```
LOST      LOST_ATTRIBUTE_STRIPPED · id c8f2a1b4-…-0004
           where p · block 7 of the before document · line 24
           text  "The Supplier shall indemnify the Customer against all losses…"
           at    div > section[2] > p[7]
           cause the tag and text are unchanged and the node kept class but no data attributes,
                 which is what a sanitiser or editor schema with an attribute allowlist does:
                 known attributes through, unknown attributes dropped
           after p at line 21 (class)
           ·     nearest surviving ancestor c1a0e0a4-…-0001
           confidence high
```

Not `3 blocks lost identity`. Not `87% of ids survived`.

- Zero dependencies, no build step, no host application, no account, no network.
- A library, an assertion for your editor's test suite, and a CLI that exits
  non-zero — so it can sit in a build pipeline.
- Runs on Node 18+ and in a browser test runner; identical answer in both.

## Why this exists

SuperDocs puts a `data-chunk-id` on every block-level element. Those identifiers
are what let an instruction target one section without touching the rest of the
document, and they have to survive the trip out to your editor and back:

> The `data-chunk-id` values are how the AI references specific sections when it
> proposes edits. When your app sends the document back on the next turn, those
> same IDs must still be on the same blocks. If they aren't, the AI's "edit
> Section 2" request lands on the wrong block — or nothing at all.
> — [Editor Integration](https://docs.superdocs.app/guides/editor-integration)

Most editor schemas and HTML sanitisers strip unknown attributes by default, so
this breaks quietly. The symptom — an edit landing in the wrong place — turns up
several steps later, in somebody else's document, a long way from the sanitiser
that caused it. The integration guide's own verification is three lines:

```js
console.assert(inIds.every(id => outIds.includes(id)), "Chunk IDs did not survive the round-trip");
```

That assert is right about *when* to check and says nothing about *what broke*.
This package is what that assert should have said.

## Install

```bash
npm install superdocs-block-identity-guard
```

No dependencies, no postinstall, no build output — the published files are the
source. To run it straight out of a clone:

```bash
git clone <this repository>
cd block-identity-guard
npm test                      # 94 tests, no install needed
node src/cli.js check fixtures/02-attribute-allowlist/before.html \
                      fixtures/02-attribute-allowlist/after.html
```

## Use it in your editor's test suite

This is the highest-value place to put it: one test, run against every block type
your product supports, and integration bugs stop reaching production.

```js
import { assertRoundTrip } from 'superdocs-block-identity-guard';

test('chunk ids survive our editor', () => {
  const incoming = '<h1 data-chunk-id="h-1">Title</h1><p data-chunk-id="p-1">Body</p>';
  editor.setHtml(incoming);
  assertRoundTrip(incoming, editor.getHtml());   // throws with the full report
});
```

A working version covering headings, lists, tables, code blocks, diagrams and
out-of-flow parts is in [`examples/editor-roundtrip.test.js`](examples/editor-roundtrip.test.js).

## Use it as a library

```js
import { checkRoundTrip, formatReport } from 'superdocs-block-identity-guard';

const report = checkRoundTrip(beforeHtml, afterHtml);

report.ok;                       // false when anything at error severity was found
report.counts;                   // { beforeBlocks, afterBlocks, intact, lost, duplicated, moved, added, partsOmitted }
report.findings[0].rule;         // 'LOST_ATTRIBUTE_STRIPPED'
report.findings[0].cause;        // the sentence naming the transformation
report.findings[0].locator;      // { id, tag, blockIndex, path, preview, line, column, parentId, partType }
report.findings[0].counterpart;  // what the block became, or null if it is gone
report.findings[0].confidence;   // 'high' | 'medium' | 'low'

console.log(formatReport(report));                    // the human report
console.log(formatReport(report, { format: 'json' })); // the machine report
```

Options: `idAttribute` (default `data-chunk-id`), `strictParts`,
`includeContentChanges`, `maxBytes`. Types ship in
[`types/index.d.ts`](types/index.d.ts).

## Use it in a build pipeline

```bash
npx chunk-guard check before.html after.html
npx chunk-guard check before.html after.html --format github --file before.html
npx chunk-guard check before.html after.html --baseline .chunkguard-baseline.json
npx chunk-guard capture stream.log --out before.html
npx chunk-guard rules
```

Exit codes are the contract:

| Code | Meaning |
|---|---|
| `0` | nothing at or above the failure threshold — including a document that was legally reordered |
| `1` | the round trip lost identity |
| `2` | the check could not run: bad arguments, unreadable file, unusable capture |

A reordered document exits `0`; a missing identifier exits `1`. The two are
different events and the exit code says so. `--fail-on` moves the threshold,
`--baseline` accepts findings you already know about so the pipeline fails only
on new ones. Full details in [docs/CI.md](docs/CI.md), a ready-made workflow in
[`examples/github-actions.yml`](examples/github-actions.yml).

## What it reports

Fifteen rules, each naming a transformation rather than a symptom. The full table
with what triggers each one and what to do about it is in
[docs/RULES.md](docs/RULES.md); `chunk-guard rules` prints it too.

| Rule | Severity | What it means |
|---|---|---|
| `LOST_ATTRIBUTE_STRIPPED` | error | Same tag, same text, identifier gone: an attribute allowlist |
| `LOST_NODE_REBUILT` | error | Text survived under a different tag: a serialisation round trip |
| `LOST_MARKDOWN_HOP` | error | Came back with no attributes at all, among neighbours that are equally bare |
| `LOST_BLOCK_REMOVED` | error | Nothing in the after document carries this text |
| `LOST_SUBTREE` | error | Everything under one surviving ancestor went the same way |
| `IDS_REGENERATED` | error | Every identifier replaced: the editor set its own content |
| `ALL_IDS_STRIPPED` | error | Every identifier gone and none minted |
| `DUPLICATE_ID` | error | One identifier on two blocks: an edit targeting it is ambiguous |
| `DATA_ATTRIBUTE_DROPPED` | error/warning | Identifier kept, diagram/equation/citation source lost |
| `DUPLICATE_ID_IN_SOURCE` | warning | The input to the round trip was already ambiguous |
| `PART_OMITTED` | info | A header/footer/footnote absent from the editor view — documented, legal |
| `BLOCK_MOVED` | info | Reordering with identity intact — not a loss |
| `NEW_IDS` | info | Identifiers that were not in the before document |
| `CONTENT_CHANGED` | notice | Ordinary editing; off unless you ask for it |
| `NO_IDS_IN_SOURCE` | error | Nothing to validate — usually a capture taken at the wrong point |

## Getting the two HTML strings

The before side is the HTML SuperDocs put on the wire: the `content` of a
`document_sync` event, or the document HTML in a chat response. The after side is
whatever your integration produces from it.

```bash
# From a saved SSE stream, a single event, or a response body:
npx chunk-guard capture stream.log --out before.html
npx chunk-guard capture response.json --document-id d1 --out before.html
```

Recipes for each surface — SSE, `/v1/chat`, a browser console snippet, and how to
capture a pair from a live session — are in [docs/CAPTURE.md](docs/CAPTURE.md).

## How it works

1. **Parse** both documents with a small tolerant parser (`src/parse.js`), so the
   answer does not depend on whether a DOM was available.
2. **Index** every element carrying the identifier, with a locator that survives
   reformatting: tag, block index, structural path, text preview, line, column,
   and the nearest ancestor that still has an identifier (`src/blocks.js`).
3. **Difference** the two sets of identifiers: intact, lost, duplicated, moved,
   new. Movement is computed against the longest run of blocks still in their
   original relative order, so one deletion does not report the rest of the
   document as moved (`src/analyse.js`).
4. **Match** each lost block to what it became, by text and then by similarity,
   preferring the most specific node (`src/match.js`).
5. **Diagnose**: the rule table turns "identifier missing" into "an attribute
   allowlist stripped it", with evidence and a confidence level (`src/diagnose.js`).
6. **Group**: losses that share a surviving ancestor collapse into one finding
   that still names every member, because one transformation caused all of them.

## What it does not do

- It does not talk to SuperDocs. No API key, no network: the input is two strings.
- It does not fix anything. It names the transformation; the fix is in your
  editor schema or sanitiser configuration.
- It does not name the specific library that stripped your attributes. It names
  the *class* of transformation, and says how confident it is.
- Table cells and deeply nested lists get a structural path and a text preview,
  which is a better locator than position alone but still not a stable identity
  for an unlabelled empty cell.
- Multi-document sessions: `capture --document-id` picks the right tree; the check
  itself compares one document at a time.

## Tests

```bash
npm test                # 94 tests: parser, analysis, rules, CLI, capture, baselines, fixtures
npm run fixtures:update # regenerate the pinned reports, then read the diff
```

The `fixtures/` directory holds eleven before/after pairs — one per failure this
tool exists to catch — and each one is pinned to its exact report in
`expected.txt`. Those pinned files are the specification: if a change makes a
report vaguer, a fixture test fails.

## Licence

MIT © Priyanshu Semwal. Built for the SuperDocs open task list, band S1,
extensions folder.
