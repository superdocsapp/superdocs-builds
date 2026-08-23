# Split a Document

Upload a master document, mark where each part begins, and get **separate clean
`.docx` files** — with a check that the parts add up to the master before you
keep them.

**Nothing is exported until the split verifies.** The claim the assignment makes
is *"split exactly at the boundaries. Nothing duplicated, nothing dropped"*, and
that is checkable, so this checks it rather than asserting it.

---

## Run it

```bash
cp .env.example .env      # add your SuperDocs key
docker compose up         # → http://localhost:8080
```

No database server, no Office host, no model stack — the image is **413MB**.
`make help` lists the shortcuts; nothing in the Makefile is a path these two
commands do not already take.

---

## How it splits

The brief asks for one clean, independently exported document per section
**"using our existing multi-document creation primitive"**. Both halves are
real here:

1. **Slice.** `POST /v1/documents/export` accepts a raw `html` body with no
   `session_id`, so cutting is stateless — slice the parsed HTML at block
   boundaries and export each slice. The master is never copied or mutated.
2. **Create.** Each exported part is then registered as a **real SuperDocs
   document** with its own durable id, and all of them are gathered into one
   session with `POST /v1/sessions/{id}/documents/open`. A part is something a
   reviewer can reopen, edit or share — not just a download.

### Two findings that cost a rewrite

The first version of this tool did step 1 only, on the strength of an audit
that concluded the multi-document primitives were "not needed". That audit had
**probed the API instead of reading it**. `GET /openapi.json` on the live API
returns 77 routes, and nothing in this repository had ever opened it. The
primitive is `POST /v1/sessions/{id}/documents/open`; the route the audit named,
`POST /v1/sessions/{id}/documents`, is **405 — GET only**.

The second is worse, because it fails silently:

> **`durable_document_id` is per session slot, not per upload.** Upload three
> parts into one session and all three come back with the *same* id, each
> overwriting the last. Three files, correct count, correct sizes — all of them
> the third part, and no error anywhere.

Each part therefore gets its own session. Measured 2026-08-16; both findings are
in [`docs/SUPERDOCS_CONTRACT.md`](../../docs/SUPERDOCS_CONTRACT.md) §8 and
`PROGRESS.md`.

| Step | Cost |
|---|---|
| Upload the master | free — the parsed HTML comes back on the upload response |
| Mark split points, preview parts (`/split`) | **free** — nothing is exported, so moving a boundary costs nothing |
| Export (`/export`) | one operation **per part** |
| Register each part as a document, gather them | free |

`MAX_PARTS` (default 10) guards against a mis-click marking forty headings and
quietly spending forty operations.

---

## Marking where the parts begin

Set **how many parts** you want, then click in the document itself. `n` parts
needs `n − 1` markers: the document already has a beginning and an end.

The preview is the document, not a summary of it — SuperDocs' own parsed HTML,
rendered at the paper size from the source `.docx` (`page_setup`: 8.5×11 with
1.25" side margins gives a 576px column), with a line-number rail and a rule
where each page ends.

### Word, or exact character

Two granularities, because clicking precisely between two letters is fiddly
with a mouse and most splits do not need to:

| | |
|---|---|
| **the start of a word** (default) | Clicking anywhere inside a word cuts before it. `Inde\|mnification` becomes `8. \|Indemnification` |
| **the exact character** | Cuts precisely where you click, mid-word and all — `8. Inde\|mnification` |

**Clicking where there is no word does nothing.** The gap between two
paragraphs resolves to a text node — usually the end of the one above — and
cutting there would start a part with a blank. A position with only whitespace
around it is not a split point, so it is ignored rather than snapped somewhere
the reviewer did not click.

The cut is drawn **at the character**, not across the paragraph: a caret on the
exact spot, and a dashed rule from there to the end of the line — the shape of
what the next part takes. The first version drew a rule the full width of the
block, which showed the *line* and nothing more, so a cut inside a word looked
identical to one at the paragraph's start and the precision was invisible.

Clicking inside "Indemnification" in exact mode cuts there:

```
part 2 ends   … remedy arises at law or in equity.8. In
part 3 starts demnificationBeta Logistics LLC shall indemnify…
```

The marker list shows each cut as `8. In|demnification`, so a mid-word cut is
visible rather than rounded away to the nearest paragraph.

### Page and line numbers are ours, not Word's

**The API carries no page or line numbers** — only `data-chunk-id` per block.
So the preview paginates: it measures every rendered line with
`Range.getClientRects()` and numbers them. Fonts and widow rules mean our page 2
may be Word's page 3.

That does not affect correctness, and the reason is worth stating plainly: **you
point at content, not at a coordinate.** A click on "Warranties" cuts at that
word whatever page Word later puts it on. The page and line labels are a name
for a position, never the position itself — which is `(chunk_id, offset)`, where
`offset` counts characters in the block's text nodes. That is exactly what the
browser's caret API reports and exactly what the Python side cuts at, so no
coordinate is translated between them.

---

## The completeness check

`coverage()` reads the parts back and compares them to the master **three ways**,
because each catches what the others miss:

| Check | Catches |
|---|---|
| block ids | a block dropped, or landing in two parts |
| characters | text lost *inside* a block — a slice that mangled markup keeps its block count |
| headings | structure lost while the words survive |

It is recomputed from the parts, not from the indices that produced them:
checking the slicing arithmetic against itself would pass for any bug in it.
A split that fails is **refused before anything is exported**, so no operations
are spent producing files that look right and are not.

Cutting mid-paragraph makes two of those checks subtler, and both were wrong
until a real split exposed them:

- A cut block becomes **two** blocks, so the part count legitimately exceeds the
  master's. `blocks_cut` counts the difference instead of flagging it.
- A cut **inside a heading** leaves two heading fragments, so the heading count
  legitimately *rises*. Exact equality reported `-1 heading(s) lost` — a
  negative loss, which is the arithmetic saying the invariant was wrong.

The character count is the one that never bends: 3865 in the master, 3865 across
the parts, however many times a paragraph is cut.

### Headers and footers

A header is not *at* a position in the document; it repeats on every page.
Slicing it into part 2 alone would leave parts 1 and 3 with no letterhead. So
page furniture is **carried into every part** and reported separately —
`repeated_furniture`, never counted as duplication, because "2 blocks
duplicated" on a correct split is a false alarm a reviewer learns to ignore.

---

## Measured

On `fixtures/conflict_pile/01_msa.docx`, cut three ways at heading boundaries,
through the running service:

```
master   24 blocks, 12 headings

part 1    8 blocks in →  8 paragraphs out, 4 headings, 1170 chars   '1. Parties and Agreement'
part 2    8 blocks in →  8 paragraphs out, 4 headings, 1412 chars   '5. Services'
part 3    8 blocks in →  8 paragraphs out, 4 headings, 1283 chars   '9. Warranties'

blocks    24/24   COMPLETE
headings  12/12   ALL PRESERVED
text      3865 master  vs  3865 across parts   NOTHING LOST OR DUPLICATED
```

Three real `.docx` files, ~37KB each, verified by opening each one and counting
its paragraphs and heading styles — not by trusting the API's answer. Three
**distinct** durable document ids, gathered into one session.

Driven end to end through the React interface in a real browser, not only
through `curl`: upload → set 3 parts → click on *5. Services* and inside the
word *Indemnification* → the preview, the marker list and the verdict update
live → Export. The verdict reads

    25 parts-blocks from 24 (1 cut mid-paragraph), 13 headings from 12 (1 cut),
    3865 characters — nothing dropped, nothing duplicated.

---

## The stated limit

Split points come from **real Word heading styles**. A `.docx` yields them; a
`.pdf` or `.md` yields none. The document can still be split — at block
boundaries rather than headings — but the outline will be a flat list. That is
a property of the source format, and `/health` says it rather than leaving a
reviewer to discover it.

---

## What is stored

| | |
|---|---|
| `data/db/splitter.db` | one table — the split log: which document, which part, how many blocks and headings, which file, and **whether the coverage check passed** |
| `data/parts/` | the exported `.docx` files |
| `data/logs/` | the log as CSV, one click |

The master's content lives in memory for as long as the tab is open and is gone
when the process stops. A folder of `.docx` files proves nothing on its own; the
log is where "nothing dropped, nothing duplicated" is written down for the split
that produced them.

The CSV neutralises leading formula characters — a heading beginning `=` would
otherwise execute when the log is opened in Excel. `data/` is gitignored in
full: a part file is a slice of somebody's contract, verbatim.

---

## What is tested, and what is not

| Layer | Automated | How |
|---|---|---|
| Block parsing, nesting, void tags | **Yes** | `tests/` — on the recorded master, no key, no network |
| Slicing: contiguity, order, repeated or out-of-order marks | **Yes** | `tests/test_slicing.py` |
| The completeness check catching a drop, a duplicate, and lost text | **Yes** | by damaging a correct split on purpose |
| Header/footer repetition not counted as duplication | **Yes** | `tests/test_slicing.py` |
| Cutting HTML mid-word: tags closed and reopened, entities never halved, nothing lost at any offset | **Yes** | `tests/test_slicing.py` |
| One paragraph cut more than once | **Yes** | `tests/test_slicing.py` |
| Marker arithmetic, ordering, page box from real page setup, the `\|` quote | **Yes** | `ui/src/split.test.ts`, no browser needed |
| Word snapping, and that a click with no word around it is refused | **Yes** | `ui/src/split.test.ts` — including `&nbsp;`, which `\s` does not match |
| The live export and the multi-document registration | **Demonstrated, not asserted** | they spend operations, so the suite never calls them — the numbers above are from a real run |

---

## Standalone

This folder is a complete project. It imports `service._portable`, which is a
**copy** — see `portable.toml` — so `cp -r use-cases/doc-splitter` into another
repository is the entire procedure. Two copied files, not five: the splitter
reads a document and talks to SuperDocs, and carries no PII or model stack.

```bash
uv run python scripts/sync_portable.py --check    # copies are current
```
