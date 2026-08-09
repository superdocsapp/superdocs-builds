# PROGRESS.md

## 2026-08-08 — Kickoff

- Shares synthetic GovCon fixtures with `task1-agentic-system` (solicitation, amendments, Q&A, in-flight proposal draft).
- No SuperDocs API key available yet — blocking real integration testing. Plan: use SuperDocs agent self-signup (`POST /v1/agents/signup`) to get a dev/test key, independent of the user's own required hands-on web-app usage.
- Not yet started: no code written.

## 2026-08-09 — Core build complete, tested against the live API

- All `delta_applier/` modules written: models, parsing, diff_engine, section_mapper,
  superdocs_client, integrity, log_generator, orchestrator, cli.
- Full test suite (`pytest`, `FakeSuperDocsClient`, no live key needed): 18 passed —
  parsing, diff engine, section mapper (incl. second-order + direct-wins merge),
  integrity hashing, and an end-to-end orchestrator suite (auto-approve, full reject,
  partial-batch reject-one-keep-rest, log generation).
- Ran the real CLI (`python -m delta_applier.cli run --auto-approve`) against the live
  SuperDocs API with the dev key. 7 deltas detected, 5 sections impacted (4 direct +
  1 second-order), all 5 section edits proposed/approved/applied, docx exported, log
  written. Confirms the 4-call contract (upload → chat/async → poll → approve → export)
  works end to end on real infrastructure, not just the fake.

### Real-API gotcha found (not in the docs): `data-section-id` does not survive upload

SuperDocs re-chunks an uploaded document on ingest and stamps each chunk with its own
`data-chunk-id` (a UUID it generates), **discarding** whatever `data-section-id`
attribute the source HTML had. So a naive design that references our own section id
in the edit instruction, or that re-extracts sections by `data-section-id` for the
untouched-section proof, silently fails — the first live run showed the one truly
untouched section (`SEC-VOL2-PASTPERF`) coming back as `MISSING`/`MISSING` in the
proof table on *both* sides, i.e. the extraction regex never matched even the
pristine pre-edit html.

Verified empirically (`data-chunk-id` values before vs. after a real edit job) that
SuperDocs's own chunk ids **are stable** across edits for chunks that weren't touched
by that edit. Fix: `DeltaApplierRun.load_proposal()` now builds a
`section_id -> chunk_id` map right after upload, by zipping our original
`data-section-id` order against the returned `data-chunk-id` order (same document,
same chunk count and order). `_build_instruction()` and `verify_untouched()` both
address the live document by `data-chunk-id` when this map is populated, falling back
to `data-section-id` when it isn't (e.g. `FakeSuperDocsClient` in tests preserves our
own attribute, so the fallback path is what the test suite exercises). Re-ran the live
CLI after the fix: `SEC-VOL2-PASTPERF` now verifies untouched with matching before/after
hashes.

Lesson for the write-up: document ids you author are not guaranteed to survive a
round trip through a third-party document-editing platform's own chunking model —
build the mapping empirically from what the API actually returns rather than assuming
attribute pass-through, and verify assumptions like "ids are stable across edits"
against the live API before relying on them for anything used as proof.

## Next steps

1. Write `README.md` for this build folder (screenshot placeholder, credit line per
   the round's CONTRIBUTING.md convention).
2. Prepare the PR for the public repo (Task 2 submission).
3. Shift primary effort to Task 1 (the agentic document-pile system) — no code written
   there yet.
