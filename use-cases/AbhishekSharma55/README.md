# Abhishek Sharma — two builds on SuperDocs

Two projects, one shared client layer, one fictional universe.

| | |
|---|---|
| **[weekly-digest/](weekly-digest/)** | One standing document, revised in place week after week instead of regenerated. One billable operation per week. Fourteen invariants, re-derived from the document's bytes, catch drift; a control arm regenerates the same digest from the same inputs, with the method committed before the result. |
| **[gdd-editor/](gdd-editor/)** | A chat-driven editor for long, linked game design documents — mechanics, narrative and art bible as sub-documents, with image support. The graded scenario runs as one command and is asserted from the documents' own bytes. |
| **[bugs.md](bugs.md)** | Fifteen SuperDocs bugs and rough edges found against the live API, with reproduction steps and two runnable repros — plus eight of my own. |
| **[Makefile](Makefile)** | `make setup` · `make test` (no key) · `make demo` (no spend) · `make scenario` / `make run` / `make control` (capped). |
| **[WALKTHROUGH.md](WALKTHROUGH.md)** | What each build does, the decisions behind it, where it is weakest, and the answers to the questions those invite. |

Both corpora are **synthetic**. *Nebula Drift* and Vantage Nine Studios do not
exist, nor do the people in them.

---

## Run everything

```bash
cd use-cases/AbhishekSharma55
make setup      # venv + install; works with pip or uv, no key needed
make test       # 62 tests, no key, no network, ~0.05s   <- start here
make demo       # re-verifies every saved week, shows a week-over-week diff,
                # and prints the last graded-scenario result. Spends nothing.
make replay     # re-runs the WHOLE 52-week digest from committed fixtures,
                # no key and no network, reproducing the live run exactly.
```

`make replay` is the one to try if you are sceptical. Every live call this repo
made was recorded to `fixtures/` with the key redacted, so the run driver
executes end to end on a machine with no key and no network.

**What that does and does not prove, stated precisely.** It proves the code path
runs offline and that every recorded response is committed. It does *not* prove
a byte-identical re-run: the instruction for week N is built from week N-1's
document, so the moment a replay diverges it asks for a request that was never
recorded and stops with a `ReplayMiss` naming the missing call. That is the
honest behaviour — a replay that silently substituted a near-miss would be worse
than one that stops.

Then, with a key in `.env` (see [`.env.example`](.env.example) — an agent can
sign itself up in one `curl`):

```bash
gdd scenario --live                          # build 2, the graded scenario   ~6 ops
digest run   --weeks 52 --max-ops 90 --live  # build 1, arm A
digest regen --weeks 12 --max-ops 40 --live  # build 1, the control arm
digest report                                # the cost comparison
```

Every command that spends operations takes `--max-ops` and stops cleanly on it.
Every long-running command resumes. Exports and uploads are free and used
heavily; only `/v1/chat` is billable.

---

## The layer underneath: `superdocs_kit/`

Not a wrapper for its own sake. Four things had to be true before either build
could be honest:

| Guarantee | Where |
|---|---|
| An operation is never spent without a durable ledger line, and the cap is checked *before* the call | `budget.py` |
| A key never reaches a log, a fixture, or a commit | `secrets.py` |
| The tests run with no key and no network | `transport.py` — record/replay |
| "Only the intended section changed" is **proved from the bytes**, not taken from the API's own summary | `docdiff.py` |

`docdiff.py` is the piece worth reading. It rebuilds `{chunk_id → exact outer
HTML}` from a document by converting `html.parser`'s line/column positions into
byte offsets and slicing the original string — so the comparison is byte-exact
rather than round-tripped through a serialiser that would normalise away the
differences it is looking for. On top of that:

- **`residue_map`** blanks each chunk's nested children, so editing one table
  cell reports *one* changed section rather than three (cell, row, table) — while
  a table whose own border changed is still reported. No tag-name special cases;
  it falls out of the containment structure.
- **`sections`** is driven by heading *positions*, so a heading the API wrapped
  in a `<div>` — which it does — is still a section.

## The three gotchas, handled

| Gotcha | Where it lives |
|---|---|
| Proposed-change content arrives as a JSON-encoded string needing a second parse | `changes.py:deep_parse` — unwraps JSON-in-a-string at any depth, bounded, applied to *every* container the API returns changes in, not just the field where I met it |
| Large operations take 30 s to several minutes with no progress | 900 s timeouts on chat, job polling with progress logging, and an automatic fallback from `/v1/chat` to `/v1/chat/async` on a gateway timeout |
| Budget your operations | `budget.py` — hard cap checked before spending, `--max-ops` on every looping command, small-sample modes, and a ledger that is the resume point |

## Honesty notes

- Everything measured is measured with the server's own `usage.ops_charged`.
  Nothing is estimated.
- Raw data is committed: both ledgers, every week's document, every export,
  every diff, and the instruction and output of every failed attempt.
- `bugs.md` ends with eight bugs of **my own**, kept in the same file, because
  a bug log that only contains other people's bugs is a marketing document. Four
  of the eight (M5–M8) are places where my own checking or accounting said a
  thing was fine when it was not: an archive parser that skipped a row it could
  not read, a surgical check that waved new content through, an archive summary
  that described the wrong week while every structural invariant said clean, and
  an operation spent without a ledger line on the one path this README promises
  is always on the ledger. All four were found the same way — comparing what the
  system said against something outside it — all four are fixed. They are the
  ones I would read first.
- Where a build has a limitation, it is in that build's README under *"What is
  honestly absent"* rather than left for a reader to discover.

## Multi-document: what is here, and what is honestly absent

Build #2 is a **multi-document** editor and the multi-document behaviour is
real: a GDD plus three linked sub-documents, a fourth created at runtime, edits
addressed to one named document, and a cross-document proof that the documents
nobody named came back **byte-identical, whole**. The link graph is data
(`corpus.LINKS`).

**What is absent is SuperDocs' own multi-document session, and the reason is
`bugs.md` B10.** Open three documents into one session and the roster comes back
with **one** entry, every document carrying `document_id: "doc_primary"`, and a
different document on each identical GET. `focus` then rejects the durable id it
was opened with. There is no id that addresses a specific open document, so a
targeted cross-document edit has nowhere to land.

So this build gives **each document its own session** and holds the link graph
itself. Two runnable, zero-operation reproductions are committed, and both were
re-run against the live API while writing this:
`repro/B10-multidoc-roster.sh` (curl) and `gdd probe-multidoc --live` (the same
sequence through this client, ending in a printed verdict).

**What that costs, said before anyone asks:** the model never sees two documents
in one turn, so a cross-document request is decomposed by my code into one
targeted edit per document rather than reasoned about in a single turn. That is
why the graded scenario's ACT 2 and ACT 3 are two operations each. If B10 were
fixed, the right architecture is different and I would change it.

MIT, per this repository. Built with Claude Code.
