# Progress

## 2026-08-06 — Stage 1

**Decisions made:** Use `extensions/Madhumasa84/sdx/`, npm, Node 20+, strict TypeScript, Commander for CLI parsing, Zod for runtime contracts, AJV only as a development-time JSON Schema validator, ESLint, and the built-in Node test runner. Keep CLI, commands, core, REST access, configuration, sessions, security, and presentation layered.

**Assumptions:** Current SuperDocs REST endpoint paths and detailed response shapes are intentionally unknown until Stage 2 documentation verification. Stage 1 uses no credentials and makes no network API calls.

**Files created:** Project instructions; design/task/progress/readme documents; exit-code and test-matrix docs; npm/TypeScript/ESLint configuration; v1 JSON Schema; CLI and layer contracts; unit/integration tests; fixture/live-test guardrail readmes.

**Commands run:** Repository instruction/layout inspection; `git status`; `npm install`; `npm run build`; `npm run typecheck`; `npm run lint`; `npm test`; compiled `sdx --help`; compiled `sdx --version`; `npm pack --dry-run`; temporary local npm-bin installation smoke check. Verification used installed Node v20.20.2 because the system-default Node v12 is below the declared engine floor.

**Verification results:** Dependency installation completed with zero reported vulnerabilities. Build, strict type check, and lint passed. All 8 baseline tests passed, covering help, version, honest placeholder failure, completed/awaiting/malformed JSON envelopes, and human/JSON presentation separation. Compiled help and version smoke checks passed. The package dry-run includes the compiled bin and schema, and a temporary local npm install executed `sdx --version` successfully.

**Deferred work:** All live REST integration, streaming transfer implementation, editing, approval application, export, profiles, credential storage, persistent sessions, retry logic, completions, and recorded/live API tests belong to Stages 2–5.

**Known risks:** API capabilities and response shapes remain unverified; JSON and exit-code contracts may require an explicitly versioned revision after documentation discovery; cross-platform stream and credential-store behavior is not yet proven.

**Stage 1 status:** Complete and preserved; all baseline checks remained passing before and after Stage 2.


## 2026-08-06 — Stage 2

**Decisions made:** Follow the current public OpenAPI-backed pre-signed path: `POST /v1/uploads` (`purpose=document`) → signed PUT without Authorization → `POST /v1/uploads/{upload_id}/process`. Start review-mode jobs at `POST /v1/chat/async`, poll `GET /v1/jobs/{job_id}`, route HITL batches only to `/approve`, route `continue_prompt` only to `/continue`, and use `POST /v1/downloads` plus a signed streaming GET for the CLI export. The API client also exposes direct binary `POST /v1/documents/export`. Authentication remains environment-only through `SUPERDOCS_API_KEY`.

**Documentation consulted:** Current `llms.txt`, `llms-full.txt`, public `openapi.json`, Documents, Async Jobs, Human-in-the-Loop, Agent Editing Playbook, Error Codes, Rate Limits, and JavaScript Examples. Exact URLs, fields, transitions, and mismatches are recorded in `docs/api-contract.md`; verified 2026-08-06.

**Assumptions and deviations:** The Documents guide foregrounds multipart upload, but the full reference/OpenAPI explicitly supports the required pre-signed document flow; Stage 2 uses that exact contract. `JobMetadata` and approval/continuation success objects are partly unconstrained in OpenAPI, so relevant guide-defined fields are explicitly validated and actual completion is proven by later polling. Fixtures are contract-derived, not recorded production traffic. The Stage 1 output change definition gained optional documentation-proven `operation`, `chunkId`, and `explanation` fields without changing existing required properties.

**Files created/updated:** Added API schemas/errors/client, pending-change normalizer, job state machine, edit command service, verified API-contract documentation, deterministic fixture server, optional capped live smoke, and Stage 2 unit/integration tests. Updated CLI wiring, redaction, output schema, package scripts, README, design/task/progress/test-matrix documentation, and fixture/live labels.

**Commands run:** Stage 1 preflight (`build`, `typecheck`, `lint`, `test`, help/version); current documentation/OpenAPI retrieval and inspection; `npm ci`; `npm run build`; `npm run typecheck`; `npm run lint`; `npm run test:unit`; `npm run test:integration`; `npm run test:fixture`; `npm test`; compiled help/version; `npm run test:live`; `npm pack --dry-run`; temporary local npm installation and installed-bin version smoke.

**Verification results:** The pre-edit Stage 1 suite passed 8/8. Clean install added 118 packages, audited 119, and reported 0 vulnerabilities. Build, strict type-check, and ESLint passed. Unit: 24/24. Integration: 30/30. Fixture-only: 27/27. Combined: 54/54 with zero failures/skips. Compiled help and version passed. Package dry-run produced `sdx-superdocs-cli@0.1.0` with 63 entries (30,822 bytes), and the locally installed `sdx --version` returned `0.1.0`.

**Live smoke:** `SUPERDOCS_API_KEY` was absent. The separate live command skipped honestly: 1 skipped test, 0 live API edits, 0 potentially billable operations, no output path. Pending human verification is not an offline Stage 2 failure.

**Security review:** No API key flag exists. Tests prove Authorization is required on API routes and absent from signed upload/download routes. Source and export bytes use Node streams; product code has no whole-document `readFile` or Base64 document transport. Signed queries, bearer values, nested credential-like fields, and explicit secrets are redacted. JSON mode produces one stdout object; progress/prompts stay on stderr. Failed exports remove temporary files and never create a partial final output. No live response, signed URL, real identifier, credential, or private document was recorded.

**Deferred work:** Stage 3 owns durable profiles/sessions, programmatic approval commands, polished section diffs, stdin/new workflows, and shell completions. Stage 4 owns bounded retry/backoff with jitter, idempotency/restart recovery, broader stream stress, and cross-platform hardening.

**Known risks/unresolved issues:** Approval/continuation 200 response shapes are published as generic objects; subsequent polling is the verification authority. A sanitized live run may reveal response additions not represented by the contract-derived fixtures. Full rate-limit retry and idempotency behavior remain intentionally deferred.

**Stage 2 status:** Implementation and offline acceptance are complete; retained as the only in-progress stage pending review. Live smoke is pending human execution with an existing environment key.

## 2026-08-06 — Stage 3

**Status:** Complete offline. Stage 3 live verification is pending because `SUPERDOCS_API_KEY` is absent and the prerequisite Stage 2 live smoke has not passed. No Stage 3 live operation was attempted.

**Implemented:** Replaced the Stage 2 command wiring with the complete Stage 3 surface: polished `edit`, streamed file/stdin `new`, explicit `approve`, auth/profile/session management, deterministic bash/zsh/fish completions, and local-only `doctor`. Added strict profile precedence, a hidden 0600 credential fallback, atomic 0600 named-session/pending-job stores, source-path/SHA-256 reuse guards, immediately persisted pending metadata, exclusive-by-default atomic exports, and honest SIGINT reporting.

**Presentation and JSON:** Added section/heading-aware terminal diffs with paragraph/list boundaries, document/change metadata, removed/added styling, ANSI CSI/OSC and control sanitization, TTY-only colour with `NO_COLOR`/`--no-color`, and explicit configurable truncation counts. JSON remains schema version `1.0`; optional `data`, `diagnostics`, and change `documentId` fields are backward-compatible additions. JSON commands never prompt and emit exactly one stdout object.

**API decisions verified:** Re-read current OpenAPI and the Sessions, Files, Documents, Multi-Document Sessions, HITL, Async Jobs, Model Selection, and export documentation. Named aliases reuse the caller-chosen persistent `session_id` without re-upload. Optional session/durable document IDs are retained only when returned because the pre-signed process OpenAPI does not require them. Supplied text for `new` follows the documented verbatim-load guidance through the proven pre-signed path instead of an approval-bypassing AI-authored turn. Exact sources and caveats are in `docs/api-contract.md`.

**Offline verification:** Node v20.20.2 / npm v11.16.0. `npm ci` added 118 packages, audited 119, and reported 0 vulnerabilities. Build, strict type-check, and ESLint passed. Unit: 35/35. Integration: 55 passed, 0 failed, 1 skipped (`jq` unavailable), 56 total. Combined Stage 2/3 fixture: 52 passed, 0 failed, 1 skipped, 53 total. Full `npm test`: 90 passed, 0 failed, 1 skipped, 91 total. The skip is only the conditional real-`jq` pipeline test; all JSON isolation tests otherwise passed.

**Packaging and tools:** Compiled help and version (`0.1.0`) passed. `npm pack --dry-run` reported 123 files, 64.7 kB packed and 434.2 kB unpacked. A fresh temporary npm-prefix install ran the installed `sdx --version` and Bash completion successfully. Bash completion passed `bash -n`; zsh and fish scripts generated and were content-tested, but their syntax tools were unavailable. `jq` was unavailable, so no real jq pipeline was claimed.

**Live status:** `SUPERDOCS_API_KEY` absent. `npm run test:live` skipped its Stage 2 prerequisite test: 1 skipped, 0 API calls, 0 edits, 0 potentially billable operations. Stage 3 edit/new live checks were not run, in accordance with the prerequisite rule.

**Security review:** No API-key option, embedded real key, credential in profile/session state, live response, or private document was found. Secret-like strings are fixture/test placeholders only. API Authorization remains absent from signed storage. Document/stdin/export bytes use streams; Base64 is limited to the documented export-warnings header. Outputs do not overwrite by default; source overwrite is forbidden; explicit overwrite atomically renames. Tests prove complete approval decisions, no implicit approval, no remote delete/archive on alias removal, terminal-control neutralization, JSON stdout isolation, restrictive permissions, corrupt-state errors, and temporary-file cleanup. No test temp directory remained. JSON files parse and no trailing whitespace was found.

**Known limitations:** Permission behavior is proven on the Linux filesystem used by tests; OS keychain integration and broader cross-platform proof remain future work. The public approval/continuation success schemas remain generic. Optional production response additions still require a sanitized live observation. The uncommitted Stage 1/2 checkpoint means every candidate file remains untracked, so literal `git diff --stat` is empty.

**Deferred to Stage 4:** Bounded retry/backoff and rate-limit policy, idempotency keys, remote cancellation, automatic interrupted-job recovery/resume, 120-page streaming/backpressure proof, and broader cross-platform hardening. Stage 4 was not started.

## 2026-08-06 — Stage 4 Milestone 1: central retry policy

**Implemented:** Added one injectable retry policy used by authenticated API requests and atomic signed downloads. Application 429 responses branch on status plus `Retry-After`, honor documented seconds, retain usage headers, and fail promptly when the delay exceeds the configured command budget. Infrastructure non-JSON 429 responses use bounded exponential backoff with full jitter. Transport and 500/502/503 retries are limited to read-only polling and atomic signed downloads; ambiguous writes are not repeated. Retry diagnostics go to stderr and structured attempt/rate metadata stays inside the existing JSON error envelope.

**Validation:** Node 20.20.2 under isolated `HOME=/tmp/sdx-stage4-preflight-home`. Build, strict type-check, and ESLint passed. Unit suite: 41/41 passed, including six deterministic retry tests with injected sleeper/clock/randomness and no real sleeping. Compiled fixture retry suite: 4/4 passed, proving application-429 attempts 2, over-budget attempts 1, infrastructure-429 attempts 3, transient polling job calls 5, and exactly one chat submission.

## 2026-08-06 — Stage 4 Milestone 2: idempotency and ambiguous outcomes

**Contract finding:** The current public OpenAPI 2.0.0 contains 77 paths and no documented idempotency or request-identifier header. `sdx` does not send or invent `Idempotency-Key` and does not claim exactly-once delivery.

**Implemented:** Added `~/.sdx/operations.json`, a 0600 atomic write-ahead ledger. It stores random operation IDs, SHA-256 hashes of stable source/instruction inputs, session/job IDs, requested export metadata, and lifecycle state; it never stores raw instructions, document bytes, credentials, or signed URLs. `submission-started` is durable before `/v1/chat/async`; `acknowledged` plus `job_id` is durable before polling. Ambiguous transport failures become `unknown`, retain exit 22 with structured recovery metadata, explicitly forbid resubmission, and block later duplicate work for that session.

**Validation:** Build, strict type-check, ESLint, and the full compiled integration suite passed: 61 passed, 1 conditional jq skip, 0 failed (62 total). Dedicated resilience fixtures: 6/6 passed. A server accepting chat then dropping the response produced exactly one chat submission, an unknown ledger record with no job ID, no raw instruction, and a blocked second invocation. A drop before acceptance was also conservatively not retried.

## 2026-08-06 — Stage 4 Milestone 3: restart recovery and concurrency

**Implemented:** Added `sdx resume [job-id]` with unambiguous persisted selection, same-job polling, repeated explicit HITL/continuation handling, completed-job export recovery, expired-job guidance, and no replacement submission. Added bounded inter-process locks using atomic lock directories, 0700 lock ownership metadata, PID-aware stale recovery, and two-second acquisition limits. Profile, credential, session, pending-job, and ledger read-modify-write mutations are locked. Named edit/new/approve/resume workflows hold a per-session lease; aliases hash to separate lock paths. Added an entrypoint interrupt latch so Ctrl+C cannot race command-specific abort setup.

**Validation:** Build, strict type-check, and ESLint passed. Unit suite: 44/44 passed, including lock contention, dead-owner recovery, and 12 concurrent session writes with no lost records and 0600 state. Dedicated compiled resilience/restart suite: 10/10 passed. Full compiled integration suite: 65 passed, 1 conditional jq skip, 0 failed (66 total). The kill/restart test proves one chat submission, one resumed job ID, explicit approval, one export, and final `download-completed` ledger state. Same-session concurrency produced one chat call; different-session concurrency produced two. Expired resume produced one original chat call and no replacement.

## 2026-08-06 — Stage 4 Milestone 4: 120-page styled DOCX proof

**Implemented:** Added a deterministic test-only DOCX generator with 120 unique page markers, 119 explicit page breaks, headings/body text, multiple inline styles and colours, lists, tables, headers/footers with Word page fields, embedded PNG media, and a page-120 target. Added `npm run test:stress`, a five-iteration compiled-binary workflow that streams upload/download through signed routes, submits one targeted edit, explicitly approves every proposal, exports atomically, validates OOXML and the edited marker, proves the source unchanged, and records sanitized raw measurements in `docs/evidence/stage4-stress.json`.

**Validation:** Stress suite 1/1 passed across five workflow iterations. Every iteration had exactly one chat submission, one approval request, and one export request. Input/upload were 202,611 bytes with SHA-256 `84c608877844eb4d83c6cd1e3e283ea400390990ac5a87e781b2b0c2d70b5780`; output was 202,611 bytes with SHA-256 `8e0cdb54357b3a9f46237f17a50738827df422fd5986b30428dddc16b7375b9c`. Uploads arrived in 4–5 chunks with a maximum observed chunk of 65,536 bytes and no fixture-side whole-document retention. Final wall time was 237.444–271.661 ms (median 262.156 ms); peak RSS was 92,608–93,284 KiB (median 93,052 KiB). No iteration failed.

**Measurement limitation:** `unzip` validated the ZIP/OOXML, 119 explicit page breaks, 120 markers, styles, lists, tables, header/footer, media, and target. LibreOffice/soffice was unavailable, so rendered page count was not measured and is not claimed. The method and small-sample p95 limitation are documented in `docs/stress-method.md`.

## 2026-08-06 — Stage 4 Milestone 5: sanitized record/replay

**Implemented:** Added an opt-in recording fetch wrapper and one-edit live recording driver. Recording requires both `SDX_RECORD_FIXTURE=1` and an existing `SUPERDOCS_API_KEY`, accepts only JSON API bodies, excludes all non-API/signed-storage traffic, caps `/v1/chat/async` at one call, replaces unstable IDs/timestamps/URLs/usage values, omits authorization and command fields, writes atomically with 0600 permissions, and rejects credential/signed-query patterns or oversized/invalid interactions. The driver generates and removes a disposable synthetic document, uses explicit item approval, exports, then writes only the validated cassette.

**Provenance:** No live credential was available and no recorder operation was run. The checked-in replay cassette is explicitly labeled `contract-derived from public SuperDocs documentation; not live-recorded`; the recorded-live cassette remains missing and is not claimed.

**Validation:** Credential-free replay/recorder suite 5/5 passed. It proves both opt-in guards, signed-storage exclusion, one-edit cap, ID/content/credential sanitization, unsafe-cassette rejection, 0600 atomic writes, and local replay with no credential or external network. A guarded `npm run record:live` invocation without the flag/key failed before network activity as designed.

## 2026-08-06 — Stage 4 Milestone 6: resilience matrix and deny-by-default recovery

**Implemented:** Expanded deterministic faults to cover application/infrastructure 429, transient 500/502/503, malformed and partial JSON bodies, HTML gateway errors, connection drops before/after chat acceptance, interrupted signed upload, killed polling, job completion before export, expiry, repeated review/continuation rounds, truncated/expired downloads, output protection, lock contention/staleness, and same/different-session concurrency. Every recovery test asserts remote call counts. Atomic downloads now remove orphan temporary files only when their owner PID is dead.

**Recovery audit:** Split upload-prepared, upload-completed, and document-processed into accurate callbacks. The ledger stores safe path/hash/size/media type plus opaque upload/document IDs, but never signed URLs or raw instructions. Added `approval-decided` and `continuation-decided` states before those calls. Resume now refuses remotely applied changes unless local state proves an explicit decision; it never converts server-side application into implicit approval.

**Validation:** Build, strict type-check, and ESLint passed. Unit suite: 45/45. Dedicated compiled resilience matrix: 22/22. Combined resilience plus original Stage 2 vertical slice: 49/49, including all 12 vertical-slice subtests. Stage 3 plus resilience earlier passed 46 with one conditional jq skip. Documentation now covers retry classification, actual at-most-one automatic-submission guarantee, ledger/restart/locking, stress method/evidence, cassette provenance, stable exit codes, and backward-compatible v1 JSON error details.

## 2026-08-06 — Stage 4 final verification

**Environment and install:** Node v20.20.2 / npm v11.16.0 under isolated `HOME=/tmp/sdx-stage4-final-home`. `npm ci` added 140 packages, audited 141, and reported 0 vulnerabilities. Build, strict TypeScript type-check, and ESLint all passed.

**Exact test results:** Unit 45/45. Complete integration 82 passed, 0 failed, 1 skipped (`jq` unavailable), 83 total. Original Stage 2 vertical slice 27/27. Stage 1–3 fixture target 52 passed, 0 failed, 1 `jq` skip, 53 total. Credential-free replay 5/5. Dedicated restart/concurrency/fault matrix 22/22. Five-iteration stress target 1/1. Complete `npm test`: 127 passed, 0 failed, 1 `jq` skip, 128 total.

**Compiled/package checks:** Compiled help, version `0.1.0`, `resume --help`, doctor JSON (11 diagnostics), and schema compilation passed. Bash/zsh/fish completions were non-empty and included `resume`; Bash passed `bash -n`. zsh/fish/jq/LibreOffice/soffice were unavailable and are not claimed. Final `npm pack --dry-run`: 147 files, 93.2 kB packed, 559.7 kB unpacked. A temporary installed package returned `0.1.0`, exposed resume help, and generated Bash completion. Package inspection proved tests, node_modules, generated DOCX, and `docs/evidence` are excluded while runtime docs are included.

**Live and recording status (updated 2026-08-07):** Both live verification operations are now complete and verified.

- **Stage 2 prerequisite live smoke:** Job submitted via `npm run test:live`. Result: `awaiting_approval`, exit 3. Exactly 1 potentially billable edit. No approval or export performed. Passed.
- **Stage 4 large-document live proof:** Job ID `74c1257e-82ae-438b-a356-460b210ce111`, session `sdx-live-stage4-06c42e8e-ecb5-4db8-8dae-8de06a0eb552`. Submitted by Codex run against the 120-logical-page DOCX fixture. The job reached `awaiting_approval` after ~45 minutes (slow-job flag active). Exactly 1 proposed change returned: `change_id=56daf0c4-8c7c-4978-bbf5-2fd4b708ba1f`, operation `edit`, `SDX_TARGET_PAGE_120_ORIGINAL` → `SDX_TARGET_PAGE_120_EDITED`. The change was explicitly approved by the human operator. Job completed at progress 100%. Export downloaded atomically: 228,906 bytes, SHA-256 `18fb807cedd4db429153accd5b11b7c4cbff4750fe6fe1a8cf44c483dcf51779`. OOXML verified: valid ZIP, `[Content_Types].xml` present, 119 explicit page breaks confirmed, `SDX_TARGET_PAGE_120_EDITED` present exactly once, `SDX_TARGET_PAGE_120_ORIGINAL` absent. No temporary files remain.
- **Total potentially billable operations: 2.** No resubmission, no cancellation, no additional edit.
- **Live cassette:** Not recorded. The contract-derived cassette remains the only cassette present and is honestly labeled as such.

**Final security review:** Repository scan found no private-key/common real-token patterns, no credential or live signed-query pattern in recordings/evidence, no candidate `.env`, generated DOCX/tarball/temp artifact, or trailing whitespace. API authorization remains absent from signed storage; document bytes stay streamed; operation state excludes raw instructions/signed URLs/document bytes; resumed application requires persisted explicit-decision proof; ambiguous chat is never blindly resubmitted; partial outputs never finalize; dead-owner download temporaries are cleaned on recovery. Fixture-only placeholder bearer/signed-query values remain intentionally synthetic and are validated as non-production data. The live output DOCX is stored in `docs/evidence/live-stage4-output.docx` and contains no credentials, signed URLs, or raw instruction text.

**Stage 4 status:** Complete. Offline implementation and acceptance complete; live large-document proof complete and verified; rendered page count remains unverified (LibreOffice/soffice unavailable — structural 119 page-break count confirmed instead). No commit, push, branch, PR, Stage 5 release, or remote destructive/cancellation operation was performed in this session.
