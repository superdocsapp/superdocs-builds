# Abhishek Sharma — two builds on SuperDocs

Two projects, one shared client layer, one fictional universe.

| | |
|---|---|
| **[weekly-digest/](weekly-digest/)** | One document, fifty-two weeks, **edited** every week and never regenerated. One billable operation per week. Thirteen invariants catch drift; a companion measurement compares it against regenerating the same digest, with the method committed before the result. |
| **[gdd-editor/](gdd-editor/)** | A chat-driven editor for long, linked game design documents — mechanics, narrative and art bible as sub-documents, with image support. The graded scenario runs as one command and **passes 18/18 in 6 operations**. |
| **[bugs.md](bugs.md)** | Twelve bugs and rough edges found against the live API, with reproduction steps and one runnable repro script. |
| **[Makefile](Makefile)** | `make setup` · `make test` (no key) · `make demo` (no spend) · `make scenario` / `make run` / `make control` (capped). |
| **[WALKTHROUGH.md](WALKTHROUGH.md)** | What each build does, the decisions behind it, where it is weakest, and the answers to the questions those invite. |

Both corpora are **synthetic**. *Nebula Drift* and Vantage Nine Studios do not
exist, nor do the people in them.

---

## Run everything

```bash
cd use-cases/AbhishekSharma55
make setup      # venv + install; works with pip or uv, no key needed
make test       # 61 tests, no key, no network, ~0.05s   <- start here
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
- Two of the twelve bugs in `bugs.md` are mine, not SuperDocs'. They are in the
  list because a bug log that only contains other people's bugs is a marketing
  document.
- Where a build has a limitation, it is in that build's README under *"What is
  honestly absent"* rather than left for a reader to discover.

MIT, per this repository. Built with Claude Code.
