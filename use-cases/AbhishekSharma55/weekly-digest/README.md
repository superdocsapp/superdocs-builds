# Weekly digest — one document, fifty-two weeks, edited and never regenerated

Every team with a recurring written update has the same problem. Week 1 you
write a nice document. Week 30 you are copying last week's file, deleting the
old content, pasting in the new, and the formatting has quietly rotted. The
reader opens a *different* document every week and has to find their bearings
again.

This is the other approach: **one standing document, revised in place every
week for a year.** The reader opens the same familiar file. Last week's content
moves into a compact archive. The formatting is the formatting it started with.

And because "it's cheaper too" is the kind of claim that needs a number rather
than a paragraph, there is a control arm that regenerates the same digest from
the same inputs, and a measurement with the method written down first.

Built on the SuperDocs REST API. Synthetic corpus — a fictional game studio,
*Vantage Nine Studios*, shipping a fictional game.

---

## Run it

```bash
cd use-cases/AbhishekSharma55
python -m venv .venv && . .venv/bin/activate      # or: uv venv && . .venv/bin/activate
pip install -e ".[dev]"                            # or: uv pip install -e ".[dev]"
cp .env.example .env                               # paste a key

digest run   --weeks 52 --max-ops 90 --live        # arm A: edit in place
digest regen --weeks 12 --max-ops 40 --live        # arm B: the control
digest report                                      # the cost comparison
```

Offline and free, no key needed:

```bash
digest verify            # re-check every saved week from its bytes
digest diff --week 30    # what changed between week 29 and week 30
pytest                   # 52 tests, no key, no network, 0.04s
```

`digest run` is safe to re-run: it resumes from `state.json` and the ledger, and
it stops cleanly on `--max-ops` rather than blowing a budget.

---

## What one week costs, and what it does

**One operation.** A SuperDocs operation covers up to 25 edited sections, so the
whole week — status line, three standing sections, the new archive row, and a
quarterly archive rollup when one is due — rides a single billable call. That is
the entire cost argument, and it is why the archive policy folds rows *inside*
the weekly edit rather than in a separate maintenance pass.

The instruction that does it splits responsibility on one line:

> **Facts are transported. Prose is generated.**

Everything the digest *asserts* — what shipped, which risks are open, what is
next — is passed through verbatim from the week's input record. The model is
never asked to recall or paraphrase a fact, because a paraphrased fact is a
fabricated fact and somebody makes schedule decisions off this document.

What *is* delegated to the model is the genuinely generative part: reading the
sections the document currently holds and compressing them into one archive row,
and folding four old archive rows into one. Those are summarisation tasks with
the source material right there in the document, and they are exactly what a
word processor cannot do.

## The archive stays navigable

Newest first. At most 8 detailed week rows; when a ninth would appear, the
oldest 4 are folded into one rolled-up row **in the same operation**, so keeping
the archive readable costs nothing.

Over 52 weeks: **18 rows instead of 51**, with 11 rollups firing at weeks 10,
14, 18 … 50. That is proved offline in
[`../tests/test_transport_and_archive.py`](../tests/test_transport_and_archive.py)
— all 52 weeks simulated in milliseconds, asserting that every past week is
accounted for exactly once and the table never grows without bound. Getting that
wrong on the live API would have cost 52 operations to discover.

## Drift, and how it is caught

Thirteen invariants, re-derived from the document's own bytes after **every**
week. None of them ask the API whether it did the right thing.

| Group | Catches |
|---|---|
| **structure** | a heading renamed, duplicated, reordered, or a header row leaking into a table body |
| **fidelity** | the bullets and every table cell must match the week's input *verbatim* — this catches paraphrase drift, the dangerous kind, invisible to a reader without the source |
| **formatting** | the risk table still bordered, its header still shaded, rows still alternating |
| **growth** | the archive accounts for every published week exactly once and stays inside its row budget |

When a week fails, the runner spends **a second operation** re-issuing the same
instruction on a reloaded copy of the last known-good document. If that also
fails, the week is rolled back rather than left corrupt. **Every repair is
counted in the cost measurement**, because reporting arm A's cost without its
failures would be measuring a system that does not exist.

Results: [`out/arm-a-edit/drift-report.md`](out/arm-a-edit/drift-report.md),
per-week documents in `out/arm-a-edit/html/`, free Markdown exports in
`out/arm-a-edit/md/`, week-over-week unified diffs in `out/arm-a-edit/diff/`.

## The cost measurement

Method first, in [`METHOD.md`](METHOD.md) — committed before the numbers were
collected, including **what would falsify the claim**. Results appended by
`digest report` into [`MEASUREMENT.md`](MEASUREMENT.md); the code that builds it
concatenates the method above the results so a number can never appear above the
method that produced it.

Unit: **billable operations**, from `usage.ops_charged` on each response. Not
tokens, not wall-clock, not my estimate — the number the customer is invoiced
in, reported by the server.

Raw data committed: both ledgers (`ledger.jsonl`, every call with its ops and
seconds), both `records.json`, every week's HTML, every export, every diff, and
the instruction and output of every failed attempt in `out/arm-a-edit/failed-attempts/`.

## SuperDocs surface used

| Call | Used for | Billable |
|---|---|---|
| `POST /v1/documents/upload-base64` | seed week 1 verbatim | no |
| `POST /v1/chat` (`pro`/`deep`, `response_mode: full`) | one edit per week | **yes** |
| `POST /v1/documents/export` | Markdown + `.docx` every week | no |
| `POST /v1/chat/async`, `GET /v1/jobs/{id}`, `POST /v1/chat/{id}/approve` | the human-gated path in `superdocs_kit/client.py`; the fallback when a sync turn hits a gateway timeout | yes |

---

## Decisions worth arguing with

**The client owns the document of record.** Every turn re-asserts the last
known-good HTML via `document_html` (a verbatim load) instead of relying on the
session to hold state. This started as a workaround — re-uploading into a live
session came back with the document duplicated, then tripled
([`bugs.md` B8](../bugs.md)) — and stayed because it made crash-resume and
rollback trivial: week N is computed from week N-1's bytes on disk and nothing
else. It costs nothing in operations (the ledger shows one per week) and it
means we stop exercising the server's cross-turn persistence. For a document too
large to fit in a request body you would invert this.

**Resume granularity is one week.** Kill the run at week 31, restart, and weeks
1–31 are skipped. Kill it *during* week 31 and that week runs again and costs
one more operation — deliberately, because a week nobody verified is a week that
is not done. The double charge is visible in the ledger rather than hidden.

**`model_tier` is pinned to `pro`.** On the default tier the five-step weekly
instruction was applied *partially* — the archive done, the four steps after it
silently dropped, four weeks running ([`bugs.md` B9](../bugs.md)). Both tiers
bill one operation, so this costs latency (~85 s vs ~20 s a week) and not money,
and both arms of the measurement use the same setting.

**One declared tolerance.** A single trailing full stop on a bullet is ignored
in the fidelity check. SuperDocs adds one perhaps one bullet in twenty and
nothing else about the bullet differs; failing the week for a period would mean
spending a repair operation to move it. It is declared in `verify.py` with the
reasoning, because a tolerance a reader cannot see is indistinguishable from a
bug.

## What is honestly absent

- **The archive summaries are not fact-checked.** The model writes them from the
  document in front of it, and I verify structure and coverage, not whether the
  20-word summary is a fair précis. That would need a second model call and a
  rubric.
- **One digest, one shape.** The sections are configuration (`document.py`), but
  a genuinely different digest — different columns, a chart — would need work.
- **Arm B is a bounded sample**, extrapolated to 52 weeks and labelled as an
  extrapolation everywhere it appears. The account has 500 operations a month
  ([`bugs.md` B7](../bugs.md)) and arm A had to be run in full.
- **Latency is not a headline.** One machine, one broadband connection, a few
  hours. The numbers are in the raw data; I do not build an argument on them.

## Files

```
data/build_corpus.py   generates the 52 weeks (seeded, reproducible)
data/weeks.json        the corpus itself, committed
weekly_digest/document.py    the seed document + the archive growth policy
weekly_digest/archive.py     what the archive should hold, computed from what it holds
weekly_digest/prompts.py     the weekly instruction and the control-arm instruction
weekly_digest/runner.py      arm A: the loop, the verification, the repair, the resume
weekly_digest/regenerate.py  arm B: the control
weekly_digest/verify.py      the thirteen invariants
weekly_digest/measure.py     method + results -> MEASUREMENT.md
```
