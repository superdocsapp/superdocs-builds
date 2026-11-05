# GDD Editor — a chat-driven editor for long, linked game design documents

Game teams do not keep one design document. They keep a spine and a handful of
sub-documents — mechanics, narrative, art bible — and the same fact ends up
written down in two of them. When a designer changes one number, somebody has
to remember every other place it appears. Usually nobody does, and the GDD
starts lying.

This is a chat-driven editor for that shape of document. You type what you want
in English; it makes the change in the right document, in the right section, and
**proves that nothing else moved.**

Built on the SuperDocs REST API. Synthetic corpus — *Nebula Drift* and Vantage
Nine Studios are fictional, as are the people in them.

---

## The scenario it is built to pass

The brief sets the bar in one sentence:

> *a reviewer asks for a new GDD section plus one linked sub-document, then
> requests a revision to one mechanic — and only the correct section changes
> across both documents.*

That sentence is executable:

```bash
gdd scenario --live
```

**Result on the live API: 20/20 checks, 6 billable operations, 542 seconds.**
The full transcript is in [`SCENARIO-RESULT.md`](SCENARIO-RESULT.md), the raw
per-check data in `out/scenario-report.json`, and the documents themselves —
before and after every act — in `out/snapshots/`.

```
ACT 1  seed 4 documents, verbatim, no model involved            free
ACT 2  "add a Traversal - Grapple Rework section, and a
        linked sub-document for it"                             2 ops (+1 repair)
ACT 3  "change the Grapple cooldown from 8 s to 5 s"            2 ops
ACT 4  concept plates into the art bible                        1 op
       prove only the intended sections moved, across all 5     free
ACT 5  export every document to .docx and Markdown              free
```

The proof in ACT 4 is the point, so it is worth saying exactly what it is. It
does **not** ask the API what it changed. Before each act every document's bytes
are snapshotted; afterwards the changed sections are re-derived from the bytes,
per document. A document nobody named must come back **byte-identical, whole**.
In ACT 3 that meant: the Grapple section changed in Mechanics, the Traversal
paragraph changed in the GDD, and `narrative`, `art-bible` and the new
sub-document were byte-for-byte what they had been.

**Two of those twenty checks exist because an earlier version of this file was
wrong**, and they are the two worth reading:

- *"the Art Bible has exactly one 'Concept art' section"* — asked to put two
  images **in** that section, the API once appended a **second section with the
  same heading** and hung the images off it ([`bugs.md` B15](../bugs.md)). Every
  surface check passed: images present, captions right, no existing section
  modified. The scenario now meets that with a targeted repair turn and counts
  the operation.
- *"ACT 2: the only new document is the linked sub-document"* — the
  cross-document report used to fail a newly created document against a snapshot
  that predated it, so `act-2` recorded `"ok": false` underneath a headline that
  said everything passed. A document that appears is now checked against the
  list of documents the act was allowed to create.

And the check underneath all of them got stricter: an act that names only
sections which already exist is no longer allowed to **add** anything either.
Both fixes are in [`bugs.md` M6](../bugs.md), with regression tests.

---

## Run it

```bash
cd use-cases/AbhishekSharma55
make setup                # venv + install, no key needed
cp .env.example .env      # then paste a key — .env.example shows both ways to get one

make scenario             # the graded scenario, end to end   (~6 operations)
# or, without the image act (~5 operations):
gdd scenario --live --quick
```

Everything else is free or offline:

```bash
gdd sections               # what the workspace holds right now  (offline)
gdd verify                 # re-check the last scenario          (offline, no key)
gdd export --format docx   # export every document               (free)
gdd probe-multidoc --live  # re-check bugs.md B10 against the API (live, 0 ops)
gdd ask mechanics "raise the Dash cooldown to 1.5 s" --only Dash   # 1 operation
```

`gdd ask --only <sections>` names the sections an edit is allowed to touch and
prints a PASS/FAIL derived from the bytes. That is the whole product in one
command.

### The human gate

```bash
gdd review mechanics "raise the Dash cooldown to 1.8 s and the Overheat pulse to 7 s" \
    --accept "1" --live
```

Proposes the changes, pauses, prints the diff, and takes a decision **per
change** — `--accept "1"`, `--accept all`, `--accept none`, or interactively.
This is the third call of the four-call contract
(`chat_async` → `jobs/{id}` → `approve` → `jobs/{id}`).

**What it verified, and how strong each claim is:**

- **Denying one change does not discard the others.** Reproduced every time.
  Two changes proposed, one approved, one denied, and the document came out with
  the approved edit applied and the denied one absent. That is the behaviour the
  approve endpoint promises, and it delivers.
- **The gate caught a genuinely mis-targeted edit — once.** Asked to change the
  Dash and **Overheat pulse** cooldowns, the model once proposed the second
  change against the **Grapple** section instead, with a confident explanation
  ([`bugs.md` B13](../bugs.md)). Every section in that document has a row
  labelled `Cooldown`, so the wrong one looked right. **Two later runs of the
  same instruction targeted correctly**, so it is intermittent — the entry says
  so, and a review UI cannot be designed assuming it fires every time.
- **A denied change still costs an operation**, because the turn is billed when
  it is submitted. This path spent that operation without a ledger line until a
  verification pass caught it ([`bugs.md` M8](../bugs.md)); `gdd review` now
  reports it.

---

## What it does

**Chat-driven authoring.** Plain-English instructions against a named document.
No form, no schema, no template — `gdd ask narrative "give Vex a reason to lie
in Act I"` is a valid edit.

**Multi-document.** A GDD (`gdd`) plus linked sub-documents (`mechanics`,
`narrative`, `art-bible`), and new ones created at runtime — ACT 2 creates a
fifth. The link graph is **data**, in `corpus.LINKS`: adding an "audio bible"
is a dict entry, not a code change.

**Images.** Concept plates are uploaded via
`/v1/documents/images/upload-base64` and embedded into the Art Bible by chat.
The plates are generated in pure Python (`images.py`, `zlib` + `struct`, no
Pillow), so a fresh clone makes its own with nothing installed. They are
honestly labelled placeholders — a gradient with a silhouette, not concept art.

**Export.** Every document to `.docx`, `.pdf`, `.md`, `.html` or `.txt`. Free,
so the workspace exports on every scenario run.

**Surgical proof.** Every edit can declare the sections it is allowed to change,
and the result carries a verdict computed from the document, not from the API's
summary.

## SuperDocs surface used

| Call | Used for | Billable |
|---|---|---|
| `POST /v1/documents/upload-base64` | seed each document verbatim | no |
| `POST /v1/chat` (`pro` / `deep`, `response_mode: full`) | every edit | **yes** |
| `POST /v1/documents/images/upload-base64` | concept plates → stable URLs | no |
| `POST /v1/documents/export` | `.docx` + Markdown of every document | no |
| `GET /v1/documents`, `POST /v1/sessions/init`, `GET /v1/sessions/{id}/documents`, `.../focus` | the multi-document session — **not used for editing**; driven by `gdd probe-multidoc --live`, which re-checks bugs.md B10 for zero operations. See below | no |

The four-call minimum contract — upload → chat → approve → export — is all
here and all exercised live. `gdd review` runs the approval path end to end:
`POST /v1/chat/async` with `approval_mode: "ask_every_time"`, poll
`GET /v1/jobs/{id}` to `awaiting_approval`, `POST /v1/chat/{session}/approve`
with per-change decisions, poll to `completed`. The scenario itself runs
`approve_all`, because a reviewer typing an instruction *is* the gate there.

One thing worth knowing before building a review UI: **the operation is billed
when the turn is submitted, not when it is approved**, so a denied change still
costs.

---

## The decision worth arguing with: one session per document

SuperDocs has a multi-document session. `/v1/sessions/init` takes a list of
document ids, `/v1/chat` takes a `document_id` to target one of them. That is
the surface this build should have used.

I could not make it hold. Opening three documents into one session returns a
roster of **one**, every entry carries the same `document_id: "doc_primary"`,
and four identical GETs returned a *different* document each time. The suggested
escape — `focus` one document, then work on it — does not exist either: `focus`
**404s on the durable id the session was just opened with** ("not open in this
session"), and accepts only `doc_primary`, which cannot distinguish one document
from another.

So there is no id that addresses a specific open document, and "change the
Grapple cooldown in Mechanics and nothing else" has nowhere to land.

**Both claims are runnable, and both cost zero operations:**

```bash
gdd probe-multidoc --live                 # this client, ending in a verdict
../repro/B10-multidoc-roster.sh           # the same sequence in curl + jq
```

Re-run three times while writing this; it reproduces every time, with fresh
documents and a fresh session. The write-up is [`bugs.md` B10](../bugs.md).

So every document gets **its own session**, and this code holds the link graph.
That is the difference worth being precise about: **multi-document is present
and working here** — four documents, a fifth created at runtime, per-document
edits, byte-identical proof for the ones nobody named — and it is implemented
in this repo rather than by SuperDocs' multi-document session, which is absent
for the reason above.

**What that buys:** every edit is addressed to exactly one document by
construction — a cross-document instruction cannot smear across files by
accident. Each document's before/after bytes are local, so the surgical check is
per-document and independent.

**What it costs, plainly:** the model never sees two documents at once, so it
cannot reason across them in one turn. A cross-document request is decomposed by
`Workspace` into one targeted edit per document — which is why ACT 2 and ACT 3
are two operations each rather than one. If the roster bug were fixed I would
use the real multi-document session and let the model see the whole workspace.

---

## What is honestly absent

- **No cross-document consistency engine.** If you change the cooldown in
  Mechanics and never mention the GDD, the GDD keeps saying the old number.
  The scenario changes both because the instruction changes both. Detecting
  divergence automatically is the obvious next build and it is not here.
- **No conflict handling for two people editing at once.** Single-writer only.
- **The images are placeholders**, generated locally. The image *path* is real —
  upload, stable URL, embedded `<img src>`, exported into the `.docx` — the art
  is not.
- **The scenario is one path.** `gdd ask` is general, but only the scripted
  scenario is asserted end to end.
- **Model tier is pinned to `pro`/`deep` here**, unlike the sibling build. The
  sibling could drop to the default tier once its instructions became literal
  HTML; this one asks the model to *author* prose, so the ambiguity cannot be
  removed the same way and the stronger tier stays. It costs latency, not
  operations ([`bugs.md` B9](../bugs.md)).

## Files

One note on reading `out/`: **`out/docs/` is the workspace's *current* state**,
which includes the `gdd review` demo run after the scenario (so Mechanics shows
`Dash 1.8 s`, and `Overheat pulse 6 s` because that change was denied). The scenario's own record is `out/snapshots/` — the byte-exact
before and after of every act — plus `SCENARIO-RESULT.md` and
`out/scenario-report.json`. The snapshots are what the surgical checks were
computed against.

```
gdd_editor/corpus.py      the four seed documents + the link graph (data)
gdd_editor/workspace.py   multi-document workspace: sessions, edits, snapshots
gdd_editor/scenario.py    the graded scenario, executable and asserted
gdd_editor/review.py      the human gate: propose, diff, approve/deny per change
gdd_editor/images.py      pure-python PNG concept plates
gdd_editor/cli.py         the `gdd` command
out/                      every artefact the last run produced, committed
```

Tests for the machinery underneath live in [`../tests/`](../tests/) — 64 of
them, no key and no network, 0.04 s by pytest's own clock.
