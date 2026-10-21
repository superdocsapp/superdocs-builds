# Task 2 Test Plan



## Domain reasoning



\- role evidence parsing — implemented (Phase 4; offline, no SuperDocs)

\- title independence — implemented (metamorphic title-swap tests)

\- typed title-versus-evidence conflict — implemented (generic seniority overstatement, management-title mismatch, and understated-scope kinds; title never assigns family, track, or level)

\- family similarity — implemented (lexicon labels applied after corpus-level clustering)

\- career-track assignment — implemented (people-management evidence, not title)

\- level inference — implemented (canonical IC1–IC5 and M1–M3; unoccupied M2/M3 remain in the catalog)

\- corpus clustering — implemented (TF-IDF + occupational cosine, compatibility gate, title excluded)

\- clustering diagnostics — implemented (cohesion, separation, nearest cluster, label confidence, bridges, unclustered members)

\- cluster defensibility — implemented (incompatible functional evidence must not merge without cross-domain scores)

\- title-independence of clustering — implemented (signature, neighbors, and membership survive title rename)

\- evidence provenance — implemented (source excerpts on supporting/counter evidence)

\- confidence calculation — implemented (coarse buckets, not fake precision)

\- provisional assignment — implemented (sparse, hybrid, title/evidence conflict)

\- misfit assignment — implemented (outside supported architecture)



Phase 4 tests cover both synthetic corpora with the same engine. Reasoning source files are checked for fixture IDs, organization names, and corpus-specific branches. Hybrid, sparse, and misfit roles are asserted unclustered rather than absorbed for coverage.



## Architecture generation



\- family definitions — implemented (canonical catalog; occupied families exposed by `build_architecture`)

\- corpus-level clusters — implemented (`ArchitectureResult.clusters` / `.clustering`)

\- level definitions — implemented (IC1–IC5, M1–M3)

\- career tracks — implemented (IC and people-manager)

\- competency matrices — implemented (constrained per-family catalog; generic when evidence is thin)

\- role profiles — implemented (structured sections; misfits are review artifacts)

\- dependency graph — implemented (level → `level_expectations`, competency → `core_competencies`)



## Adversarial cases



\- misleading senior title with junior scope

\- modest title with senior scope

\- hybrid role spanning families

\- sparse job description

\- contradictory responsibilities

\- management title without people responsibility

\- highly specialized role outside standard architecture



## Surgical propagation



\- impacted profiles identified — implemented (`analyze_level_change`)

\- unaffected profiles excluded — implemented (only explicit level dependencies)

\- correct dependent section updated — implemented (`level_expectations` only for a level change)

\- dimension-surgical field update — implemented (`changed_dimensions` + patch only corresponding rendered fields)

\- fallback wording for unchanged dimensions preserved — implemented (no opportunistic rewrite)

\- unrelated sections preserved — implemented (hash comparison)

\- unchanged level-expectation fields preserved — implemented (per-field raw-line comparison)

\- preservation hashes stable — implemented (`PreservationReport`; unexpected changes are errors)

\- rejected SuperDocs review does not apply domain update — implemented (`review_outcome=rejected`, `mutation_applied=false`, `domain_applied=false` even if remote job status is completed)

\- domain apply is verification-gated — implemented (`finalize-domain` requires approved mutation, `mutation_applied=true`, structure pass, preservation pass; remote `completed` is not enough)

\- domain apply is idempotent and keeps rejected history — implemented

\- completed remote job is not a successful mutation — implemented (resume uses `review_outcome` + `mutation_applied`, not `status=completed` alone)

\- rejected surgical attempt remains retryable — implemented (new `live-edit:surgical:N` operation; rejected attempt kept in history)

\- mixed review is partial, not full apply or blind retry — implemented (`review_outcome=mixed`, `partial_mutation=true`)

\- repeated propagation is safe — implemented (second plan is empty; second apply is a no-op)



## Human review



\- changes enter pending state — SuperDocs adapter implemented (offline); reviewer web Review screen uses the same explicit approve/reject model locally

\- approve applies accepted changes — adapter submits explicit per-change decisions

\- reject leaves content unchanged — adapter sends `approved=false`

\- partial decision handling — mixed item-level decisions; `ApprovalResult.all_approved` is false unless every item is approved

\- completion blocked while required decisions remain — polling stops at `awaiting_approval`; nothing is auto-approved

\- publication remains explicit — export is a separate call and is not implied by job completion



## SuperDocs



Offline contract tests (`tests/test_superdocs_*.py`) use `httpx.MockTransport`. They do not read `SUPERDOCS_API_KEY` and must not call the live API.



\- upload — implemented (`POST /v1/documents/upload`, default `open_mode=new_focused`)

\- multi-document session — implemented (session roster + explicit document ids)

\- document targeting — implemented (`document_id` on reviewed edit). Export does **not** target by document id; current docs require `html` / `session_id` / `upload_id`.

\- search — implemented as async chat with `cross_session_search=true` (no dedicated search endpoint in the official API)

\- template use — implemented (`POST /v1/templates/upload-base64`, `GET /v1/templates`)

\- async edit — implemented (`POST /v1/chat/async` with `approval_mode=ask_every_time`)

\- awaiting approval — implemented (poll `GET /v1/jobs/{job_id}`; distinguish HITL vs `continue_prompt`)

\- approve — implemented (`POST /v1/chat/{session_id}/approve`)

\- reject — implemented (same endpoint, `approved=false`)

\- export — implemented (`POST /v1/documents/export` with documented `html` + `session_id` + `format` + `filename`/`options.filename`; empty HTML fails before HTTP; streamed bytes; empty/JSON bodies are failure)

\- proposed-change double JSON parse — implemented (`parse_pending_changes`)



Live smoke (manual only, not pytest): `python scripts/superdocs_smoke.py`



Live verification CLI (manual only, not pytest): `python scripts/superdocs_live.py …`



Offline Phase 7A orchestration tests (`tests/test_live_orchestration.py`, `tests/test_export_selection.py`, `tests/test_live_review_resume.py`, `tests/test_live_profile_baseline.py`, `tests/test_profile_structure.py`) use `FakeProtocolClient` where HTTP would otherwise be required. They do not read `SUPERDOCS_API_KEY` and must not call the live API.



\- live DOCX artifacts — implemented (deterministic `python-docx` generation from corpus markdown + templates)

\- multi-document upload — implemented (four JD DOCX files; roster asserts distinct coexisting ids)

\- template setup — implemented (upload or reuse by filename)

\- reviewed edit stops for approval — implemented (framework / surgical / profile repair)

\- approve/reject — implemented (explicit `ReviewDecision`s only; empty decision list is an error)

\- authoritative filled-profile publish — implemented (upload deterministic DOCX; no SuperDocs fill)

\- duplicate Level expectations detected — implemented (`profile_structure` semantic marker parser; Word paragraph/run layout is not a field boundary)

\- Word layout variants of one Level expectations block — implemented (one paragraph per field; concatenated paragraph; multiple runs / `w:br`; duplicate/missing markers still fail)

\- surgical-update refuses a malformed live baseline — implemented

\- in-place reviewed profile repair — implemented (`repair-profile`; stops at human approval)

\- resume from saved non-secret state — implemented (`.runtime/` ids; no API key)

\- duplicate completed operation is not resent — implemented

\- completed + approved reviewed edit is not duplicated — implemented

\- completed + rejected reviewed edit starts a new async edit — implemented

\- awaiting_approval resumes the same job — implemented

\- mixed decisions keep partial semantics — implemented

\- process restart retains review resume semantics — implemented

\- surgical instruction targets one section — implemented (`level_expectations` only)

\- search demo — implemented (`cross_session_search=true`; graph remains surgical authority)

\- existing processing/completed search resumes without another POST — implemented

\- export — implemented (`render_framework_html` / `render_profile_html`; documented HTML export body; unknown kind fails before HTTP)

\- failed live step preserves resumable state — implemented

\- secrets never enter saved state — implemented

\- roster durable-id reconciliation — implemented (upload may omit durable id; GET roster is authoritative; known durable ids are never replaced with null; conflicting ids fail)

\- repair null durable ids without re-upload — implemented (resume matches `document_id`, copies roster durable ids, does not POST again)



Human live run: upload of four JD documents succeeded; templates passed; framework and profile live jobs were approved. The SuperDocs profile fill duplicated Level expectations; in-place repair was approved. Surgical attempt 1 was rejected (unrelated Complexity rewrite). Attempt 2 was rejected (duplicated baseline). Attempt 3 was approved (version + Scope only). Exported profile structure and preservation checks passed. Search was resumed on the same job id (no second POST) and reached `completed` with `verified=true`, `terminal=true`, and `has_result=true`. Framework export attempts 1–2 HTTP-succeeded but returned a source JD. Attempt 3 used documented HTML + `session_id` (15,650 chars); semantic verification passed (`verify-framework-structure` `semantic ok=True`). Framework reviewed edit is proven.



## Reliability



\- missing API key — implemented (`ConfigurationError`)

\- invalid API key — implemented (HTTP 401/403 → `AuthenticationError`)

\- timeout — implemented (GET → `TransientHttpError` with bounded retry; mutating timeout → `AmbiguousOutcomeError`, no retry)

\- malformed response — implemented (`MalformedResponseError` / `ProposedChangeParseError`)

\- upload failure — implemented (typed HTTP errors; mutating timeout is ambiguous)

\- async job failure — implemented (`JobFailedError`); polling timeout is `JobTimeoutError` (job may still be running)

\- approval failure — implemented (`ApprovalError`)

\- export failure — implemented (`ExportError`; no success without received bytes)

\- retry after uncertain outcome — mutating calls are not blind-retried

\- duplicate request — in-process `operation_key` returns the already-completed result

\- idempotency — not exactly-once; see README retry/idempotency section



## Security



\- API key absent from frontend — reviewer UI never receives `SUPERDOCS_API_KEY`; `/api/superdocs/status` omits the key and auth headers

\- API key absent from logs — settings/client/error repr redacts the key; auth headers are not logged

\- API key absent from fixtures — offline fake uses `sk_test_offline_not_a_real_key`

\- API key absent from repository history — `.env` is gitignored; `.env.example` has a placeholder

\- no real employee data — synthetic fixtures only



## Acceptance corpora



### Corpus A



Primary synthetic organization used during implementation.



### Corpus B



Independent synthetic organization used to prove the logic is not hard-coded to Corpus A.



## Reviewer web application



Offline FastAPI tests: `tests/test_web_api.py`, `tests/test_web_acceptance.py`. They construct `create_app(WorkspaceService(WorkspaceStore()))` and never call the live SuperDocs API.



Frontend tests (`web/`, Vitest + Testing Library) mock `fetch`. They cover navigation, corpus switching, architecture metrics, role evidence, title-conflict evidence, provisional/misfit rendering, framework level table, profile rendering, change-impact planning, before/after review, approve/reject, empty review, API error, and SuperDocs not-configured. They must not use a live SuperDocs key.
