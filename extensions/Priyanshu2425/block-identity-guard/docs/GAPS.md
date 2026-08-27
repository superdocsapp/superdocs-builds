# Gaps in the brief, and what was done about them

The build was specified as a thirty-minute S1: parse two HTML strings, difference
the identifiers, run a six-row rule table over the losses, ship a library and a
CLI. Building it surfaced problems the sketch did not cover — several of them the
kind that make a checker worse than useless, because it reports a clean document
when it should not, or fails a build for something documented as legal.

This page records each one and how it was closed. It is written as a decision
log, not an apology: every item is a place where the shipped tool deliberately
differs from the plan.

---

## 1. Out-of-flow parts would have been reported as loss

Headers, footers, footnote bodies and comments arrive as ordinary blocks carrying
`data-part-type` alongside their identifier. The documentation is explicit that
an editor may legitimately not render them, and that their absence never deletes
anything — deletion requires passing `deleted_part_chunk_ids`.

A naive set difference reports every one of them as a lost block. On a document
with headers and footers, that is a red build for behaviour the platform
documents as correct — the fastest possible way to get a check switched off.

**Closed**: `PART_OMITTED`, severity `info`, with `--strict-parts` for
integrations that do own parts. A part that is *present* but stripped is still an
ordinary loss.

## 2. The identifier is not the only attribute with this failure mode

Diagram sources, equation sources and citation fields ride on `data-*`
attributes, and the docs name the same silent failure: a schema that strips
unknown attributes degrades a diagram to an empty block on the next edit cycle.
The block keeps its identifier, so an identifier-only check calls it intact.

**Closed**: `DATA_ATTRIBUTE_DROPPED`, checked on every surviving block. Error for
attributes whose loss breaks something specific, warning otherwise, and editor
bookkeeping attributes (`data-slate-*`, `data-testid`, …) ignored entirely.

## 3. Comparing raw positions reports a deletion as a document-wide reorder

The plan's fourth rule is "id present, text and position changed → reordering
with identity intact". Implemented literally, deleting one block shifts every
index after it and the report claims the whole tail of the document moved.

**Closed**: movement is measured against the longest run of blocks still in their
original relative order (a longest-increasing-subsequence over the surviving
identifiers). Blocks outside that run are the ones that actually moved. A
deletion now produces one finding, not forty.

## 4. "Exit non-zero on any loss" contradicts reporting legal moves

The plan wanted moves reported separately *and* a CLI that exits non-zero on any
loss. Those are the same event to a shell.

**Closed**: a four-level severity model (`error`, `warning`, `info`, `notice`) and
`--fail-on`, defaulting to `error`. A reordered document exits `0`; a stripped
identifier exits `1`; a check that could not run exits `2`, so a broken check
never reads as a pass.

## 5. Matching a lost block to what it became was hand-waved

Every rule in the table — "tag unchanged", "tag changed `p` → `div`" — presumes
you have already found the after-side node that used to be the block. The plan
did not say how, and it is the hard half of the diagnosis.

**Closed**: `src/match.js`. Exact tag-and-text, then text alone, then similarity
within the same tag, then similarity across tags for text long enough to carry
the match on its own — preferring the most specific node, so a paragraph is
matched rather than the div wrapping it, and never matching the same node twice.
Match quality feeds the confidence level.

## 6. A deleted block is not a stripped attribute

The six-row table has no row for "the block is gone". Without one, a deleted
paragraph gets blamed on whichever rule matches loosest — a checker confidently
naming the wrong cause.

**Closed**: `LOST_BLOCK_REMOVED`, reached only when nothing in the after document
carries the text or anything close to it.

## 7. The input can already be broken

The plan validates the round trip and trusts the before side. If the captured
HTML already has one identifier on two blocks, nothing downstream can resolve it
and every other finding is suspect.

**Closed**: `DUPLICATE_ID_IN_SOURCE`, a warning about the capture rather than the
integration.

## 8. Two rules had no mechanism behind them

"Ids present but re-generated wholesale" and "ids absent from a whole subtree" are
in the plan's table, but neither is a per-block rule — one is a property of the
document pair, the other of a region.

**Closed**: document-level signals computed once (`IDS_REGENERATED`,
`ALL_IDS_STRIPPED`, tag-vocabulary collapse), and ancestor grouping for regions:
three or more losses sharing a nearest surviving ancestor collapse into one
`LOST_SUBTREE` finding that still names every member and its own rule. One
transformation, one finding, with the members intact — the specificity the card
is graded on survives the summarising.

## 9. The plan states causes as facts

"Id absent, text present, tag unchanged → an attribute allowlist stripped it."
Usually true. Not always: an all-attribute strip and a markdown hop leave the same
trace on a block whose neighbours are also bare.

**Closed**: every finding carries a confidence level and the evidence it rests
on, including the evidence that argues against it ("this text is not unique in the
after document, so the counterpart is the best match rather than the only one").
A tool that names a cause has to say how sure it is, or the next person debugs the
wrong component.

## 10. Serialisation noise looks like change

No two serialisers emit identical HTML. Attribute order changes, `&` becomes
`&amp;`, a non-breaking space is re-encoded, whitespace is collapsed. Compared
literally, every one of those is a text difference, and the report fills with
findings about documents nobody touched.

**Closed**: text is normalised (entities decoded, whitespace collapsed, NFC) and
attribute order is irrelevant to the parse. Fixture `01-clean-round-trip` is
exactly this case and is pinned to a clean report.

## 11. The identifier attribute was assumed

`data-chunk-id` is the SuperDocs attribute, but a capture taken at the wrong point
in a pipeline often has no identifiers at all — and answering "0 blocks lost
identity" to a document with no identifiers in it is the worst answer available.

**Closed**: `idAttribute` is configurable, and a before document with none
produces `NO_IDS_IN_SOURCE` naming any alternative attribute it did find.

## 12. Nothing in the plan lets an existing project adopt the check

Run this against an integration that has been shipping for a year and it finds
real problems that cannot all be fixed this afternoon. The check then gets
switched off, and a check that is switched off finds nothing.

**Closed**: baselines. `--update-baseline` records what is known, `--baseline`
accepts it, and the findings stay visible in the report — a baseline hides a
failure from the exit code, never from the reader. Stale entries are counted.

## 13. There was no way to get the two HTML strings

The whole input is two strings of HTML, and the plan left obtaining them to the
reader. In practice the before side is buried in an SSE stream, and capturing it
from the wrong place — reading it back out of your own store — produces a clean
report on a broken pipeline.

**Closed**: `chunk-guard capture` reads a saved stream, a single event, an array
of events or a response body, handles `focused_document_id` for multi-document
sessions, and refuses to guess. `docs/CAPTURE.md` names the two ways to capture
wrongly.

## 14. A pipeline check that only prints to a log is half a check

**Closed**: `--format github` emits workflow annotations with file, line and
column, so the finding lands on the line of the captured HTML in the pull
request. The JSON report is deterministic — no timestamps, no absolute paths — so
it can be diffed and stored.

## 15. The plan assumed a standard-library HTML parser

Written for a language whose standard library has one. The consumers of this tool
are editor integrations, which are JavaScript, and Node has no HTML parser. Using
the browser's `DOMParser` where available would make findings depend on the
environment they were computed in — the exact class of bug this tool exists to
catch.

**Closed**: a small tolerant parser (`src/parse.js`), about 330 lines, handling
what document HTML and editor serialisers actually emit: unclosed `<p>` and `<li>`,
table cells, void elements, raw-text elements, comments, doctypes, every attribute
quoting style, and a stray `<` that is text. Same answer on Node and in a browser,
and the package keeps its zero dependencies.

---

## Deliberately still out of scope

Named in the plan as "deliberately after", and still after:

- **A live capture mode** that subscribes to `document_sync` itself. `capture`
  reads what you recorded; it does not hold a connection.
- **Signature detection for named sanitiser and editor libraries** — "this looks
  like DOMPurify with the default config". The rules name the class of
  transformation, not the product.
- **A published package and a GitHub Action wrapper.** The workflow file is here;
  the marketplace action is not.
- **Table-cell and nested-list identity.** They get a structural path, a line, a
  text preview and a surviving ancestor, which beats a position index — but an
  empty unlabelled cell still has no stable identity, and the report says so by
  dropping to low confidence rather than guessing.
- **Cross-document checks.** `capture --document-id` picks the right tree out of a
  multi-document session; the check itself compares one document at a time.
