# Amendment and Q&A Delta Applier

Built by **Monisha** for the SuperDocs Round 2 task.

A GovCon proposal manager's proposal is "in flight" when the agency drops an
amendment or publishes Q&A answers mid-bid. This tool reads the new
amendment/Q&A document, diffs it against the original solicitation, works out
exactly which proposal sections are affected — including second-order
effects (a page-limit cut on the technical volume also forces a look at the
compliance matrix that cross-references it) — and stages the required edits
against the in-flight proposal draft through SuperDocs's human-in-the-loop
chat API. Every edit is annotated with the amendment paragraph that drove it.
Sections the amendment didn't touch are cryptographically proven untouched,
not just claimed. The result: an updated proposal draft, plus an
amendment-response log ready to drop into the compliance file.

## Why this is "strong," not just "done"

- **Correct affected-section mapping, including second-order effects.**
  `config/section_map.yaml` is a data-driven rule-type → section map plus a
  section dependency graph, so second-order propagation (e.g.
  `SEC-VOL1-TECH → SEC-COMPLIANCE-MATRIX`) is configuration, not a hardcoded
  special case. Direct impacts always win over second-order ones when a
  section is both.
- **Every edit traces to an amendment paragraph.** Each staged change carries
  the exact source citation (`amendment_0001.txt PARA 4`, etc.) all the way
  through to the review item and the final log.
- **Untouched sections are provably untouched, not asserted.** `integrity.py`
  hashes each declared-untouched section's text before and after the run and
  reports a per-section pass/fail with the actual hashes — see
  [`delta_applier/integrity.py`](delta_applier/integrity.py) and the gotcha
  below.
- **Deterministic core.** Parsing and diffing (`parsing.py`, `diff_engine.py`,
  `section_mapper.py`) are regex-based and have zero dependency on a live
  API key or an LLM call, so the core logic is fully unit-tested without
  network access. Only the SuperDocs chat step needs the real API.
- **Conflicts are surfaced, not silently resolved.** If a Q&A answer
  contradicts what the amendment already established, it's flagged as a
  `Conflict` for a human to resolve — the state isn't quietly overwritten.
- **Rejections are respected per-item.** Approving or rejecting one proposed
  change in a section's batch never discards the others (see
  `tests/test_orchestrator.py::test_rejecting_one_change_in_a_batch_does_not_discard_the_rest`).

## A gotcha found (and fixed) against the live API

Not documented in the task brief: `POST /v1/documents/upload` re-chunks the
document and stamps each chunk with SuperDocs's own `data-chunk-id`,
**discarding** any custom attribute the source HTML had (here,
`data-section-id`, which the fixtures use to identify proposal sections).
A first live run showed the untouched-section proof reporting `MISSING` for
the one section the amendment didn't touch — the extraction regex never
matched, on either side, because the id it was looking for no longer existed
in the document SuperDocs returned.

Verified empirically that `data-chunk-id` values *are* stable across edits
for chunks an edit didn't touch. Fix: `DeltaApplierRun.load_proposal()`
builds a `section_id -> chunk_id` map right after upload by zipping the
original `data-section-id` order against the returned `data-chunk-id` order,
and both the edit instructions and the untouched-section proof address the
live document by `data-chunk-id` from then on (falling back to
`data-section-id` when no map can be built — e.g. the in-memory test fake
preserves our own attribute). Full writeup in [`PROGRESS.md`](PROGRESS.md).

## Project layout

```
config/section_map.yaml      # rule-type -> section map + section dependency graph
fixtures/                    # synthetic GovCon solicitation, amendment, Q&A, proposal draft
delta_applier/
  models.py                  # SourceRef, ParsedFact, AmendmentDelta, Conflict, SectionImpact, ReviewItem, ...
  parsing.py                 # deterministic regex parsers for solicitation/amendment/Q&A
  diff_engine.py             # baseline state + fact application -> deltas/confirmations/conflicts
  section_mapper.py          # rule -> affected section(s), direct + second-order
  superdocs_client.py        # real SuperDocsClient (upload/chat/poll/approve/export) + protocol
  integrity.py                # untouched-section hashing/proof
  log_generator.py           # amendment-response log (compliance-file artifact)
  orchestrator.py            # DeltaApplierRun: ties it all together, one section at a time
  cli.py                     # `python -m delta_applier.cli run ...`
tests/                       # fakes.py (in-memory SuperDocs stand-in) + full pytest suite
output/                      # exported proposal + amendment-response log land here
```

## Running it

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# unit + integration tests (no API key needed — uses an in-memory fake client)
.\.venv\Scripts\python.exe -m pytest -q

# real run against the live SuperDocs API (needs SUPERDOCS_API_KEY in .env)
.\.venv\Scripts\python.exe -m delta_applier.cli run --auto-approve
```

`--auto-approve` approves every staged change non-interactively (useful for
demos/CI); omit it to get an interactive terminal review — approve/reject
each proposed change per section, same as the human-gate requirement from
Task 1's brief. See `python -m delta_applier.cli run --help` for flags to
point at your own solicitation/amendment/Q&A/proposal files instead of the
bundled fixtures.

## Test coverage

18 tests, all passing, all runnable without a live API key:

- `test_parsing.py` — solicitation/amendment/Q&A parsing against the real fixtures.
- `test_diff_engine.py` — delta production, idempotency, conflict vs. confirmation detection.
- `test_section_mapper.py` — direct + second-order impact mapping, direct-wins merge.
- `test_integrity.py` — untouched-section hashing.
- `test_orchestrator.py` — end-to-end pipeline against `FakeSuperDocsClient`: auto-approve,
  full reject (byte-identical output), partial-batch reject-one-keep-rest, and log generation.

## Evidence of a live run

This was run end-to-end against the real SuperDocs API (`--auto-approve`, no
fake client). The two artifacts it produced are committed here for review:

- [`output/amendment-response-log.md`](output/amendment-response-log.md) —
  the amendment-response log: deltas applied, staged edits with their
  approve/reject decisions and timestamps, confirmed-unchanged facts, and
  the untouched-section hash proof (`SEC-VOL2-PASTPERF` before/after hashes
  match: `af42204e1e60` == `af42204e1e60`).
- [`output/proposal-final.docx`](output/proposal-final.docx) — the exported,
  edited proposal draft, downloaded straight from the live SuperDocs API
  after all edits were approved.
