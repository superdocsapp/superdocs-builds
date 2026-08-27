# SuperDocs token-cost benchmark: whole-document regeneration vs. section-level editing

Built for the SuperDocs Round 2 task (assigned build, Task 2). This measures
— and publishes — the answer to "why not just send the whole document to a
model," instead of estimating it for marketing.

**Status: mock-mode results are committed and reproducible right now. A
real-API validation run is not yet done — see [PROGRESS.md](PROGRESS.md)
item 1 for why, and the "Results" section below for exactly what that
means for these numbers.**

## Who this is for

Positioning and developer evangelism — anyone asked "why does SuperDocs edit
targeted sections instead of just regenerating the whole doc." This repo is
the receipts.

## What it measures

A corpus of synthetic documents at 5 size tiers (roughly 1, 5, 25, 100, and
400 pages), each put through a 5-turn multi-edit session (reword, factual
fix, shrink, expand, insert), run through two arms:

- **`whole_doc`** — every edit resends the entire current document and takes
  back a full regenerated replacement.
- **`section_edit`** — every edit sends only the targeted section and takes
  back a replacement for just that section.

For every edit, in both arms: input tokens, output tokens, estimated cost,
wall-clock time, and characters sent are recorded. Sessions are multi-turn,
so cumulative session cost is measured, not just a single edit in isolation.

This is distinct from SuperDocs' existing interactive pricing calculator,
which estimates for marketing. This harness actually runs edits (mock or
real) and publishes the raw numbers.

## Method, stated before results

1. Generate the corpus deterministically (`benchmark/corpus.py`), same seed
   → same documents, so results are reproducible byte-for-byte.
2. Generate a fixed multi-turn edit session per document
   (`benchmark/edit_tasks.py`).
3. Run both arms over every document's session, through a `Client`
   (`benchmark/client.py`) — either the offline `MockClient` or the real
   `SuperDocsClient` hitting the documented four-call contract (upload,
   chat, approve, export).
4. Record one `EditRecord` per edit, per arm (`benchmark/arms.py`).
5. Write raw records to `data/results/raw_edits.csv` / `.json` — never
   overwritten silently, always the full record of what ran.
6. Build summary tables and charts from the raw data
   (`benchmark/report.py`) — nothing in the charts that isn't traceable
   back to a row in `raw_edits.csv`.

## Formats and domains this corpus covers

Synthetic Markdown documents only, in three domains: vendor contracts,
project status reports, insurance claims (see `benchmark/corpus.py`,
`DOMAINS`). A second run with `--seed` changed produces different documents
within this same declared set — same domains and format, different content
— which is what "a second run means different documents inside that
declared set" asks for.

## Results (mock mode — see caveat)

Committed in `data/results/`: `raw_edits.csv`, `summary_by_arm.csv`,
`summary_by_tier_and_arm.csv`, `variance_report.csv` (3 repeats),
`cost_vs_doc_size.png`, `cumulative_session_cost.png`.

The finding, from `summary_by_tier_and_arm.csv` (mock-mode, 3 repeats):

| tier   | arm          | mean input tokens | mean cost/edit (USD, est.) |
|--------|--------------|-------------------:|----------------------------:|
| tiny   | whole_doc    | 949                | 0.0170                       |
| tiny   | section_edit | 488                | 0.0087                       |
| medium | whole_doc    | 21,899             | 0.394                        |
| medium | section_edit | 559                | 0.0100                       |
| xlarge | whole_doc    | 192,845            | 3.471                        |
| xlarge | section_edit | 405                | 0.0072                       |

**The curve is the finding, not any single number**: whole-doc cost per
edit scales linearly with document size (tiny → xlarge is roughly a 200x
cost increase); section-edit cost per edit stays roughly flat regardless of
document size, because it only ever sends the targeted section. See
`cost_vs_doc_size.png`.

**Caveat, stated plainly**: the numbers above come from `MockClient`, an
offline deterministic stand-in (see `PROGRESS.md` item 1) — I did not have
network access to the real SuperDocs API while building this. The
*mechanism* the benchmark measures (chars/tokens sent per edit, and how
that scales with document size) is real and arm-agnostic to which client
runs it — a real API run should preserve the shape of the curve. The
*absolute dollar figures* are illustrative pricing (`metrics.py`,
`PRICING_USD_PER_1K`), not real SuperDocs costs, until a real-API run
happens. Re-running with `--mode real` and a live key replaces every number
above with a measured one; nothing about the harness changes.

## Budget guard

- `MockClient` runs cost nothing — no network, no billing.
- `--mode real` tracks cumulative *estimated* cost after every edit and
  hard-stops the run the instant it would exceed `--budget-usd` (default
  $1.00), writing whatever partial results exist rather than discarding
  them.
- Always run `--small-sample` first against a real key (1 doc, 2 turns) to
  prove the real client works before spending on the full corpus:
  ```
  SUPERDOCS_API_KEY=sk-... python3 -m benchmark.runner --mode real --small-sample --budget-usd 0.25
  ```
- **Stated cap for a full real-mode run, before running it: $2.00.** (The
  full mock-mode matrix is 300 edits; at real-API pricing this is a rough
  upper bound, not a promise — the guard will stop earlier if it's wrong in
  the expensive direction.)

## Reproducing this — one command

```bash
./run.sh
```

This creates a venv, installs `requirements.txt`, runs the offline test
suite, runs the full mock-mode benchmark (5 tiers × 2 docs/tier × 5 turns ×
2 arms × 3 repeats = 300 edits), and rebuilds all reports/charts. Takes well
under a minute, since mock mode does no network I/O.

For a real run: `SUPERDOCS_API_KEY=sk-... ./run.sh --mode real --small-sample --budget-usd 0.25`

## What "strong" would add beyond what's here

Per the card's own bar — honestly, what's not yet done:

- A real-API validation run (blocked on this build environment's network
  access, not a design gap — see PROGRESS.md item 1).
- Real per-model pricing in `metrics.py` in place of illustrative numbers.
- A fourth domain (clinical paperwork) — the corpus generator supports
  adding it as a one-line config change, just not done yet.
- The `insert` edit type's section-arm handling is a simplification (see
  PROGRESS.md item 5) that likely *understates* the real cost of true
  section insertion relative to a naive full-doc regenerate; worth a
  dedicated arm-variant if this becomes a cited number externally.

## Tests

```bash
python3 -m pytest tests/ -q
```

No live API key needed — all tests run against `MockClient`. They verify:
determinism of corpus generation, that the section-edit arm sends
dramatically less text than whole-doc on large documents (the core claim),
that untargeted sections are provably byte-identical after a section-edit
run, that the whole-doc arm never mutates the original document object, that
a missing `SUPERDOCS_API_KEY` fails clearly rather than silently falling
back, and that repeated runs are correctly labeled for variance reporting.

## Repository layout

```
benchmark/
  corpus.py      synthetic document + section generator, deterministic
  edit_tasks.py  multi-turn edit session generator, 5 edit types
  client.py      MockClient (offline) + SuperDocsClient (real REST calls)
  arms.py        whole_doc arm, section_edit arm, EditRecord
  metrics.py     token estimation heuristic + cost model (config, not code)
  runner.py      CLI: orchestrates corpus × sessions × arms, budget guard
  report.py      tables + charts from raw_edits.csv
tests/           offline pytest suite
data/corpus/     generated documents (regenerable, but committed)
data/results/    raw_edits.csv/json, summary tables, charts (committed)
run.sh           one-command reproduction
TASK.md          how this repo is organized
PROGRESS.md      assumptions and decisions, logged as made
```
