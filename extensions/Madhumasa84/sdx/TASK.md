# sdx implementation plan

## Stage 1 — Foundation and contracts (complete)

- [x] Architecture, safety invariants, JSON Schema, exit codes, strict TypeScript scaffold, and baseline tests.

## Stage 2 — API vertical slice (complete)

- [x] Current REST/OpenAPI verification.
- [x] Pre-signed streaming upload and parse.
- [x] Async HITL edit/poll/approval/continuation.
- [x] Verified signed streaming export and deterministic fixture tests.
- [x] Offline acceptance complete; optional live smoke remains pending.

## Stage 3 — CLI experience (complete offline; live pending)

- [x] Polished human edit with sanitized section diffs and explicit truncation.
- [x] Single-object JSON mode and programmatic complete decision approval.
- [x] Strict profiles, credential setup/status, named sessions, and pending-job state.
- [x] Streamed stdin/file new workflow and overwrite-safe output naming.
- [x] Bash, zsh, and fish completions plus non-billable doctor.
- [x] Compiled-binary offline tests for all Stage 3 safety boundaries.
- [x] Record the final complete verification and live prerequisite status.

## Stage 4 — Hardening and proof (offline implementation complete; live gaps pending)

- [x] Add a central injectable application/infrastructure 429 and safe-transient retry policy.
- [x] Verify no documented idempotency header; add a privacy-safe write-ahead ledger and block ambiguous resubmission.
- [x] Add explicit same-job `resume`, repeated HITL/continuation recovery, expiry handling, and completed-before-export recovery.
- [x] Add atomic 0600/0700 state, bounded locks, stale-owner recovery, no-lost-update tests, and same/different-session concurrency tests.
- [x] Prove a deterministic styled 120-logical-page DOCX through the complete offline signed streaming workflow across five measured runs.
- [x] Add opt-in sanitized recording plus credential-free contract-derived replay and secret validation.
- [x] Cover the Stage 4 deterministic resilience fault matrix with exact remote call assertions.
- [ ] Run live 120-page proof (key absent; zero operations).
- [ ] Capture a genuinely live sanitized cassette (key absent; contract-derived cassette retained honestly).
- [ ] Measure rendered 120-page count (trustworthy renderer unavailable; structural OOXML count passed).
- [ ] Prove broader OS/environment locking and permission behavior (deferred to Stage 5 matrix).

## Stage 5 — Release and submission (complete)

- [x] Finalize versioning/changelog/release evidence.
- [x] Run authorized production smoke and publish submission materials.
- [x] Verify a clean published install.
