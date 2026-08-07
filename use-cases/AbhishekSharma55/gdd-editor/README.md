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

**Result on the live API: 18/18 checks, 6 billable operations, 368 seconds.**
The full transcript is in [`SCENARIO-RESULT.md`](SCENARIO-RESULT.md), the raw
per-check data in `out/scenario-report.json`, and the documents themselves —
before and after every act — in `out/snapshots/`.

```
ACT 1  seed 4 documents, verbatim, no model involved            free
ACT 2  "add a Traversal - Grapple Rework section, and a
        linked sub-document for it"                             2 ops (+1 repair)
ACT 3  "change the Grapple cooldown from 8 s to 5 s"            2 ops
ACT 4  prove only the intended sections moved, across all 5     free
ACT 5  export every document to .docx and Markdown              free
```

The proof in ACT 4 is the point, so it is worth saying exactly what it is. It
does **not** ask the API what it changed. Before each act every document's bytes
are snapshotted; afterwards the changed sections are re-derived from the bytes,
per document. A document nobody named must come back **byte-identical, whole**.
In ACT 3 that meant: the Grapple section changed in Mechanics, the Traversal
paragraph changed in the GDD, and `narrative`, `art-bible` and the new
sub-document were byte-for-byte what they had been.

---

## Run it

```bash
cd use-cases/AbhishekSharma55
python -m venv .venv && . .venv/bin/activate      # or: uv venv && . .venv/bin/activate
pip install -e ".[dev]"                            # or: uv pip install -e ".[dev]"

cp .env.example .env      # then paste a key — see .env.example for both ways to get one

gdd scenario --live       # the graded scenario, end to end        (~6 operations)
gdd scenario --live --quick   # same without the image act         (~5 operations)
```

Everything else is free or offline:

```bash
gdd sections               # what the workspace holds right now  (offline)
gdd verify                 # re-check the last scenario          (offline, no key)
gdd export --format docx   # export every document               (free)
gdd ask mechanics "raise the Dash cooldown to 1.5 s" --only Dash   # 1 operation
```

`gdd ask --only <sections>` is the interesting one: it names the sections the
edit is allowed to touch, and prints a PASS/FAIL derived from the bytes. That is
the whole product in one command.

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
| `GET /v1/documents`, `POST /v1/sessions/init`, `GET /v1/sessions/{id}/documents` | explored for the multi-document session; **not used** — see below | no |

The four-call minimum contract — upload → chat → approve → export — is all
here. The approval path (`chat_async` + `POST /v1/chat/{id}/approve`) lives in
`superdocs_kit/client.py` and is exercised by the sibling build; this one runs
`approve_all` because a design reviewer typing in a chat *is* the human gate.

---

## The decision worth arguing with: one session per document

SuperDocs has a multi-document session. `/v1/sessions/init` takes a list of
document ids, `/v1/chat` takes a `document_id` to target one of them. That is
the surface this build should have used.

I could not make it hold. Opening three documents into one session returns a
roster of **one**, every entry carries the same `document_id: "doc_primary"`,
and four identical GETs returned a *different* document each time. There is a
runnable repro at [`../repro/B10-multidoc-roster.sh`](../repro/B10-multidoc-roster.sh)
and the write-up is [`bugs.md` B10](../bugs.md). With every document sharing one
id there is nowhere for "change the Grapple cooldown in Mechanics and nothing
else" to land.

So every document gets **its own session**, and this code holds the link graph.

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
- **Model tier is pinned to `pro`/`deep`** because the default drops steps of a
  multi-part instruction ([`bugs.md` B9](../bugs.md)). That costs latency, not
  operations, and it is a workaround for someone else's default.

## Files

```
gdd_editor/corpus.py      the four seed documents + the link graph (data)
gdd_editor/workspace.py   multi-document workspace: sessions, edits, snapshots
gdd_editor/scenario.py    the graded scenario, executable and asserted
gdd_editor/images.py      pure-python PNG concept plates
gdd_editor/cli.py         the `gdd` command
out/                      every artefact the last run produced, committed
```

Tests for the machinery underneath live in [`../tests/`](../tests/) — 52 of
them, no key and no network, 0.04 s.
