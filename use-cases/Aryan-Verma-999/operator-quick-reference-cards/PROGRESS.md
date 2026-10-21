# Progress

> **Handoff note (2026-08-20):** Historical M1 entries below predate the
> corrected `document_sync.content` parser and are not the current provider
> adjudication. The current public-safe evidence is in
> `docs/superdocs-live-bug-report.md`: 8/6 recovered and 8/31 fresh live
> synchronized/proposal chunks, both with zero direct matches and no
> approval/export.

## M0 — Live SuperDocs contract spike

Status: **live contract verified**. The local ignored `.env` was loaded without printing its contents. Authentication succeeded and the core live flow completed.

### Commands run

- Repository state checks (`pwd`, status, branch, last commit)
- Official docs/OpenAPI fetch and inspection
- `python scripts/generate_m0_fixture.py`
- `python scripts/live_contract_smoke.py --dry-run`
- `PYTHONPATH=<temporary dependency directory>:. python3 -m pytest -q` — 5 passed
- `RUN_LIVE_SUPERDOCS=1 PYTHONPATH=<temporary dependency directory>:. python3 scripts/live_contract_smoke.py` — completed after read-only reconciliation of non-billable document state
- `git diff --check`

### Offline preparation

- Fixture: `fixtures/m0-tiny-manual.pdf`; 4 pages; SHA-256 and byte size are emitted by the generator and dry-run.
- Client: strict endpoint methods, redacted logging, explicit timeouts, no mutation retries, operation budget, proposal normalization, unsafe-target rejection.
- Dry-run: zero HTTP requests by construction.
- Fixture generation is deterministic for the current generator.
- Live operation count: 1 billable async edit; local cap 2 was not exceeded.
- Contract source: fetched 2026-08-15; OpenAPI 2.0.0.

### Observed live

- Authentication: `GET /v1/sessions` → 200.
- Upload/process: `/v1/uploads`, signed PUT, `/v1/uploads/{upload_id}/process`; durable IDs were 36-character UUID-shaped values. `/v1/documents` returned `{documents,total}` and document entries used `document_id`.
- Session mapping: local slot was `doc_primary` (11 characters); durable card/manual IDs were distinct 36-character values.
- Job: `POST /v1/chat/async`; observed `awaiting_approval` then `completed` after two approval rounds. Intermediate event type: `proposed_change_batch`. Polling `metadata.pending_changes` held 3 object proposals.
- Approval: batch body with required `job_id`, top-level `approved`, and `changes` containing `change_id`, `approved`, `feedback`. First round mixed; second round approved revised proposals.
- Read-back: card exact string present, placeholders absent; manual remained a separate untouched target with version 4.
- Export: HTTP 200, `application/pdf`, no warning headers, 18,524 bytes, PDF SHA-256 `969cb69b999ab2ce766feb9ed987f808778b385e02c9921c7578bad9a1817a5e`, 1 readable page.
- Usage counters were not returned in the reconciled job payload.

### M1 implementation

Implemented the deterministic M1 local slice: PyMuPDF page map, six typed evidence records, canonical card plan, protected two-page skeleton, sanitized M0 contract fixtures, fail-closed verifier, and sabotage tests. The exact manual hash remains `2a0bf608d483fd156e5657975eb6a19d1381bfff8719cf22208978d6e7ef7570`.

### Next milestone

M1 local/offline implementation is complete. A single explicit live attempt reached authoritative read-back but the returned card failed the local verifier, so no export was accepted and no retry was made. M1 remains blocked pending investigation/reconciliation of that live provider result.

### Reconciliation diagnosis — 2026-08-15

The worktree contained no authoritative HTML, proposal-round payloads, decisions, base HTML, final version, final hash, or structured verifier report from that attempt. The only persisted result was `RuntimeError: authoritative final card failed local verifier`. Consequently the exact failing check and observed value are unavailable; they must not be invented. This is classified as J: a local live-run observability/persistence defect, not evidence of a verifier or SuperDocs product defect. No billable retry was made. A sanitized diagnostic record is in ignored `artifacts/m1/previous-live-diagnostic.json`, and the runner now persists a bounded structured record before raising on future runs.

### Controlled retry — 2026-08-15

One retry used one operation. The run reached four approval rounds; all proposals were rejected by the local prospective verifier. Authoritative read-back returned version 1 with HTML hash `cc748c28b15020ef4394a121fc2311b38dd37d316ab469cc4ca60e7919f623c7`, equal to the unchanged base/prospective hash. `PROTECTED_STRUCTURE` and `CITATION_PAGE_POINTERS` for `SPEC-001` failed; exact specification, safety, procedure, restart, unsupported-number, and hostile-content checks passed. Manual version/hash stayed unchanged at version 4 and `7acb94276a933edddbc439c4f4519edb3d6115249ef8a3ce0cd1dab7fe51a885`. Export was not attempted. Root cause is class I: the uploaded/editor-resolved card representation did not satisfy the deterministic skeleton contract before any proposal was accepted. The sanitized regression is `tests/fixtures/m1/authoritative-failure.json`.

### M1.1 non-billable skeleton fidelity repair

No chat endpoint was called. Fresh-session Path A HTML upload and Path B blank+save both failed `PROTECTED_STRUCTURE` and `CITATION_PAGE_POINTERS`/`SPEC-001`. Visible exact value, safety, procedure, restart, and `PDF p. 3` content survived; doctype/body, page-break style, and all `data-*` metadata were stripped or rewritten. Direct PDF export was not attempted because no base passed. The direct runner now blocks before chat on an invalid authoritative base. The selected architecture correction is content staging plus local deterministic composition with an immutable sidecar.

### M1.2 staging generation — 2026-08-15

The exact-HTML export-only probe used zero chat operations and passed: HTTP 200, 2 pages, PDF SHA-256 `ed2b838d864f2fb13e27891048b74d132f19b1f8b4857ae92152830ca1133f92`, 33,612 bytes, exact value/safety/procedure/restart/citation present, no warning headers. The local parser issue described in this historical entry was later corrected; current adjudication is in `docs/superdocs-live-bug-report.md`, which records a provider proposal-to-chunk correlation defect after corrected recovery and a fresh capped run.

### Assigned-build closeout — frozen

M0 is verified. M1 is complete as the assigned-build vertical slice with a defended fail-closed cut: M0 proves live mixed review behavior, while the final M1 run rejected all ambiguous provider proposals and composed the unchanged source-locked staging content locally. The exact value, safety, procedures, citations, hostile-content, two-page HTML, exact-HTML PDF export, and PDF postflight are verified on the declared synthetic fixture. Offline tests: 24 passed. Fixture: 4 pages. Evidence records: 6. Final PDF: 2 pages. No more live operations will be spent on the chunk-mapping limitation before submission. Further implementation is intentionally stopped; M2 and extra-credit work are out of scope for this closeout.

## Continuation slice — authoritative reconciliation and M2–M5 foundations — 2026-08-16

Milestone: M1 continuation; M2/M3/M4/M5 foundations only. No M2–M6 completion claim is made.

Implementation completed:

- staging maps now persist slot ID, heading, authoritative chunk/document ID, old HTML/text fingerprints, evidence IDs, critical/editable classification, and base version;
- proposal mapping requires all supplied identity signals to resolve to exactly one slot and rejects unknown or contradictory targets;
- native-text PDF ingestion module with streamed SHA-256, magic/MIME, byte/page/encryption gates, dimensions/rotation, words/spans, images/drawings, annotations, repeated-header/footer signals, parser version, and immutable manifest writer;
- SQLite FTS5 deterministic retrieval and unique local-span mapping for semantic hints;
- typed deterministic safety flow graph with explicit branches and unsupported-number rejection;
- durable SQLite job revisions/events/idempotency/outbox schema foundation;
- React review-surface foundation and truthful batch manifest/ZIP writer;
- scale-manual generator and offline metrics entry point.

Tests run:

- `python3 -m compileall -q linecard scripts tests` — PASS;
- `git diff --check` — PASS;
- declared pytest suite — BLOCKED in the base interpreter because `pytest`, PyMuPDF, httpx, pydantic, and FastAPI are not installed;
- temporary dependency installation — BLOCKED by unavailable package index/build dependency (`setuptools`); no source or credential change resulted.

Live operations consumed: 0 in this slice. No live retry was issued.

Assumptions verified: existing M0/M1 live evidence and operation count remain unchanged; source/manual fixtures remain synthetic; no secrets or raw live responses were added.

Bugs/rough edges discovered: repository checkout is an untracked subtree under the broader `superdocs-builds` Git root; the environment currently lacks the declared Python and frontend test dependencies; the full M2–M6 gates remain unresolved.

Next slice: make the durable API/worker state transitions executable, generate and measure both synthetic manuals, add gold ledgers and retrieval/conflict tests, then run the suite in an environment with declared dependencies.

### M1 live gate attempt — 2026-08-16

Offline preflight passed and the hard live budget was set to one. The live runner made no billable chat operation: SuperDocs DNS/network resolution failed before authentication (`ConnectError: [Errno -2] Name or service not known`). Therefore the required real eligible approved proposal and live mixed final staging result remain unproven.

LINECARD M1 BLOCKED

Exact blocker: the current execution environment cannot resolve the SuperDocs API host. No retry was issued and no live result was inferred from the offline fixture.

### Offline scale/UI slice — 2026-08-16

Implementation completed: generated the committed 400-page LC-100 synthetic manual and materially different 60-page AX-200 manual with gold ledgers; added the FastAPI control-plane scaffold, React evidence/review surface, frontend lockfile, deterministic flow/storage/batch foundations, and metrics runner.

Measured raw local results:

- LC-100 400 pages, 427,152 bytes, SHA-256 `d0a2de13ab5a60e1f918dc220410aba9e028f64fcdadb2f819af518b9dcbf30b`: ingest 302.57 ms, FTS index 1.43 ms, retrieval 0.75 ms, 3 hits;
- AX-200 60 pages, 65,300 bytes, SHA-256 `c478630033bc0af4f639c47e452aa75f51f4c1cfe34f760264ba5d59408baccf`: ingest 40.86 ms, FTS index 0.34 ms, retrieval 0.16 ms, 5 hits.

Tests: Python offline suite 29 passed; `npm ci`, `npm run build`, and `npm test` passed with 1 frontend test. No Playwright suite exists yet. Generated frontend `dist/` and `node_modules/` are ignored.

M2–M6 remain unresolved: no complete gold recall evaluator, manual viewer runtime, durable worker/recovery implementation, image/diagram SuperDocs proof, bounded layout correction, real batch execution/budget reconciliation, full error/security/accessibility/fresh-clone matrix, or live contract recovery.

## Continuation — corrected M1 contract and ledger pass — 2026-08-16

The M1 staging boundary now sends the exact deterministic staging HTML as `document_html` with an explicit staging `document_id` and `approval_mode=ask_every_time`. The authoritative map is derived from `document_sync` chunk IDs, including chunk IDs on nearest owning wrappers. Proposal resolution requires direct `chunk_id`; document identity, synchronized old HTML/fingerprint, and base version are secondary integrity checks. Unknown chunks, wrong documents, stale bases, missing headings, duplicates, and contradictory old content fail closed.

The client now has ordered SSE parsing with `last_sequence`, duplicate suppression, `GET /v1/sessions/{session_id}/jobs` pending-review reconciliation, and durable local worker/outbox recovery primitives. Offline layout blocking, PDF postflight, batch sample/blocked-sibling/retry behavior, API error routes, manual evidence viewer, accessibility live status, and acceptance ledger were added.

Required DNS preflight was run once at this checkpoint:

- `getent hosts api.superdocs.app || true`: no address returned;
- `curl -fsS --max-time 10 https://api.superdocs.app/health || true`: DNS resolution failure, curl exit 6;
- billable operations consumed: 0.

Recorded status: `LIVE_GATE_DEFERRED_DNS`. This does not stop offline implementation. Python test execution is currently unavailable because `python3` has no pytest/PyMuPDF installed. Frontend build passed; frontend unit tests pass after excluding the Playwright directory from Vitest. Playwright remains a separate pending gate until its dependency/runtime is installed.

## Offline completion pass — 2026-08-16

Executed the ledger worklist without spending SuperDocs operations. Durable SQLite worker lease/restart/outbox/effect deduplication and review decision integration tests were added. The typed flow graph now validates yes/no decisions, evidence mappings, deterministic Mermaid, and sanitized diagram content. The final card contains a rendered evidence-tagged SVG flow diagram; layout exposes `PAGE_BUDGET_UNSATISFIABLE` and clipping checks. A real offline three-task batch produces isolated card artifacts, verification manifests, a batch manifest, and ZIP package. Normalized HTTP/network errors, security gates, and the richer evidence viewer were added.

Repository-local Playwright and Chromium were installed; E2E passed. A clean temporary copy passed frontend install/build/unit tests, demo, 49 Python tests, startup import, and E2E. Repeated metrics were written to `artifacts/metrics/raw.json` and `artifacts/metrics/report.md`. Docker Compose is not part of this checkout's declared architecture, so no Docker gate is claimed.

This earlier DNS-gated count is superseded by the subsequent live certification attempt below.

## Live contract certification attempt — 2026-08-16

Connectivity and authentication succeeded from the current environment. Pre-live gates passed: 49 Python tests, frontend build/unit tests, Playwright, demo, and diff check. Exactly one bounded async generation was issued with `LINECARD_LIVE_OPERATION_BUDGET=1`; it reached `awaiting_approval` and consumed one operation.

Sanitized provider evidence captured sequence 1 `document_sync`, sequences 2–6 intermediate events, and sequence 7 `proposed_change_batch`. The non-billable jobs recovery returned nine pending changes, but the provider metadata omitted the `pending_batch_decisions` key. The persisted synchronized HTML produced eight authoritative slot chunk IDs; the nine proposal chunk IDs had zero intersection. The separate SSE endpoint returned an HTTP error. The runner submitted no approval and no export, preserving the fail-closed invariant. Evidence: `artifacts/m1/live-run-sanitized.json`.

The documented non-AI M4 image proof succeeded: `/v1/documents/images/upload-base64` returned HTTP 200, exact-HTML export returned HTTP 200, the PDF contained one embedded image and rendered SVG text, and export warnings were absent. Evidence: `artifacts/m4/live-image-proof.json`.

Current live audit result: M1-01, M1-02, M1-04, M1-05, and M4-02 are live-verified; M1-03 and M1-06 are `BLOCKED_REAL_DEFECT` with exact provider evidence above. M4 Mermaid remains unresolved as a separate TODO. No second generation was issued.

### Verified provider-contract discrepancy — 2026-08-16

The prior live M1 job was recovered without generating or approving anything.
It remained `awaiting_approval`, with `document_sync` at sequence 1,
`proposed_change_batch` at sequence 7, nine pending `edit` proposals, zero
approval decisions, no export attempt, and one AI operation consumed.

The complete synchronized HTML contained nine `data-chunk-id` values. All nine
proposal chunk IDs were absent from that complete HTML. The intersection was
zero. Because direct chunk ownership is the safety invariant, LineCard blocked
approval rather than guessing a section. This is a verified SuperDocs provider
chunk-ID contract defect, not a LineCard failure. Sanitized evidence is in
`docs/superdocs-live-bug-report.md`; no session IDs, job IDs, API keys, signed
URLs, or raw provider responses are tracked.

The real event ordering is live-verified: `document_sync` sequence 1 preceded
`proposed_change_batch` sequence 7. Session-jobs recovery of the awaiting job
and nine pending changes is live-verified. Final approval, reconciliation, and
PDF export are not green and were not attempted. M4 image upload/export remains
live-verified. M4 Mermaid provider rendering remains unresolved pending an
authoritative wire-format proof.

## Handoff runtime remediation — 2026-08-20

The public reviewer path was repaired without any live provider operation.

- `pyproject.toml` now declares a setuptools build backend, the sole
  `linecard` package, FastAPI, and Uvicorn. The documented editable install now
  completes successfully.
- `make` automatically uses `.venv/bin/python` when available. `make check`
  runs Python, frontend, and browser gates; `make run` builds the frontend and
  serves the actual FastAPI reviewer flow at `http://127.0.0.1:8877`.
- The browser no longer changes local-only state. It calls API endpoints for
  evidence retrieval and inclusion decisions, source-lock verification,
  postflight-gated PDF preparation, manual download, and verified PDF download.
  A missing required safety record blocks export until restored.
- Sanitized live proof references used by the public ledger now point at tracked
  documentation instead of ignored artifacts. The provider chunk-ID defect
  remains `BLOCKED_REAL_DEFECT`; no approval, export, or retry was issued.

Validation completed:

- `scripts/fresh_clone_check.sh` — PASS;
- `make demo` — PASS (`4` pages, `6` evidence records, verifier `PASS`);
- Python tests — `53 passed`;
- frontend build and unit tests — PASS;
- served FastAPI + Playwright reviewer flow — `1 passed`;
- `git diff --check` and public secret-pattern scan — PASS.
