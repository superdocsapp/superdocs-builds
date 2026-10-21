# Progress



## Phase 0 — Specification lock



\- \[x] Assignment reviewed

\- \[x] Task 2 identified

\- \[x] Required outcomes frozen

\- \[x] Acceptance criteria frozen

\- \[x] Required SuperDocs surfaces identified

\- \[x] Non-goals defined



## Phase 1 — Repository foundation



\- \[x] Fork created

\- \[x] Fork cloned locally

\- \[x] Official repository added as upstream

\- \[x] main synchronized

\- \[x] Feature branch created

\- \[x] Project folder created under use-cases/Rahul9214/

\- \[x] Initial directory skeleton created

\- \[x] Foundation files populated

\- \[x] Repository boundary validated

\- \[ ] Foundation commit created

\- \[ ] Branch pushed



## Phase 2 — Synthetic corpus



\- \[x] Define fictional company

\- \[x] Define job-family distribution

\- \[x] Build corpus A

\- \[x] Build independent corpus B

\- \[x] Include ambiguous roles

\- \[x] Include title/scope conflict

\- \[x] Include hybrid role

\- \[x] Include sparse-evidence role

\- \[x] Validate fixture schemas



## Phase 3 — Domain model



\- \[x] Role evidence model

\- \[x] Job family model

\- \[x] Career track model

\- \[x] Level definition model

\- \[x] Competency model

\- \[x] Role assessment model

\- \[x] Misfit/provisional model

\- \[x] Role profile model

\- \[x] Dependency graph (typed `DependencyEdge` only; traversal/propagation remains Phase 6)



## Phase 4 — Architecture reasoning



\- \[x] Evidence extraction

\- \[x] Family classification

\- \[x] Corpus-level evidence clustering

\- \[x] Track assignment

\- \[x] Level inference (IC1–IC5 and M1–M3)

\- \[x] Confidence/evidence explanation

\- \[x] Misfit handling

\- \[x] Title independence tests



Phase 4 hardening: clustering uses field-weighted TF-IDF plus occupational score cosine, with a compatibility gate so distinct crafts do not merge on generic JD language. Family catalog labels a cluster only after the group exists. Same-primary roles still need content overlap; hybrid, sparse, and misfit roles stay unclustered or appear as bridges. Canonical management levels remain M1–M3.



## Phase 5 — SuperDocs integration



\- \[x] Upload

\- \[x] Multi-document

\- \[x] Search

\- \[x] Templates

\- \[x] Async reviewed edits

\- \[x] Approval flow

\- \[x] Export

\- \[x] Error handling

\- \[x] Idempotency/retry boundaries



Phase 5 implements a SuperDocs adapter under `src/job_architecture/superdocs/`. Domain reasoning still does not call SuperDocs. HTTP details stay behind `SuperDocsClientProtocol`. All pytest coverage for this phase is offline (httpx MockTransport). The live smoke script is manual and is not part of pytest.



## Phase 6 — Surgical propagation



\- \[x] Dependency detection

\- \[x] Impact analysis

\- \[x] Proposed profile changes

\- \[x] Preservation measurement

\- \[x] Review gate

\- \[x] Regression tests



Phase 6 generates a `FrameworkDocument` from architecture-domain objects: canonical IC1–IC5 and M1–M3, family competency matrices, employee-readable profiles, misfit/provisional review artifacts, and explicit `DependencyEdge` records. Level changes are planned as section-level `UpdatePlan`s, stay unapplied until approved, and are checked with deterministic section hashes. SuperDocs payload/instruction transforms exist but make no HTTP calls. Frontend remains later. Live SuperDocs publication is prepared in Phase 7A and is not complete until a human runs it.



## Phase 7A — Live SuperDocs verification preparation



\- \[x] Tiny Corpus A demo subset (IC, broader IC, manager, provisional)

\- \[x] Deterministic JD / template DOCX generation (`python-docx`, isolated)

\- \[x] Orchestration service on `SuperDocsClientProtocol`

\- \[x] Targeted framework and role-profile instructions

\- \[x] Surgical `level_expectations` instruction from the Phase 6 graph

\- \[x] Resumable non-secret `.runtime/` state

\- \[x] Manual CLI with explicit modes, intent print, and confirmation

\- \[x] Proposed-change display (id / document / before / after / reason)

\- \[x] Search and multi-document roster demonstration hooks

\- \[x] `docs/live-verification.md` template (values remain `not run` where unexecuted)

\- \[x] Offline orchestration tests against a protocol fake

\- \[x] First human live upload (four Corpus A JDs; multi-document roster ok)

\- \[x] Durable-id persistence fix (reconcile from authoritative roster; do not re-upload)

\- \[x] Live framework and profile reviewed jobs completed (human approved; profile fill left duplicated Level expectations)

\- \[x] Live surgical proposal reviewed and **rejected** (attempt 1: unrelated Complexity rewrite)

\- \[x] Second live surgical proposal reviewed and **rejected** (attempt 2: duplicated live profile baseline)

\- \[x] Dimension-surgical propagation fix (preserve unchanged rendered fields)

\- \[x] Reviewed-job resume fix: persist `review_outcome` / `mutation_applied` separately from remote `completed`; rejected attempt stays eligible for a new edit

\- \[x] Repair current `.runtime/` review fields locally (no re-upload, no SuperDocs call)

\- \[x] Profile creation uses deterministic filled DOCX; SuperDocs is not asked to regenerate decided sections

\- \[x] Structural profile validator + pre-surgical baseline gate + in-place reviewed repair flow

\- \[x] In-place reviewed repair of the duplicated live profile (`repair-profile`; human approved)

\- \[x] Export after repair approval (`exports/profile.docx`)

\- \[x] `verify-profile-structure` layout/semantic fix (initial paragraph-based run failed; marker parser passes the existing export)

\- \[x] Surgical SuperDocs proposal after a verified unique Level expectations baseline (attempt 3 approved: version + Scope only; attempts 1–2 rejected and kept in history)

\- \[x] Export + structure + preservation verification after surgical 3

\- \[x] Verification-gated local `finalize-domain` (`domain_applied` not inferred from remote `completed`)

\- \[x] Search resume poll to a proven terminal result

\- \[x] Live verification record completed (Search verified terminal; framework export attempts 1–2 failed with a source JD; attempt 3 HTML semantic PASS; framework reviewed edit proven)



Search was resumed on the same job id with no second POST. Remote status reached `completed` (`verified=true`, `terminal=true`, `has_result=true`). Surgical attempts 1 and 2 were rejected and remain in history. Attempt 3 was approved (`mutation_applied=true`). Domain apply is local and verification-gated.





## Phase 7 — UI

- [x] Corpus workspace
- [x] Architecture view
- [x] Misfit/provisional review
- [x] Role profile view
- [x] Change-impact view
- [x] Human review
- [x] Export flow
- [x] Responsive behavior

The reviewer app is FastAPI + React/Vite inside this use-case directory. It calls existing domain services. SuperDocs live export is not offered from the browser. Live Search is recorded as verified/terminal in `docs/live-verification.md`.

## Phase 8 — Verification

- [x] Unit tests
- [x] Integration tests
- [x] SuperDocs contract tests
- [x] Corpus A acceptance
- [x] Corpus B acceptance
- [x] Failure/retry tests
- [x] Secret scan
- [x] Clean-clone verification
- [x] Build verification
- [x] README finalized
- [x] Screenshots added
- [ ] Final PR prepared

Phase 9 recorded the assignment audit, manual UI acceptance, visual QA, screenshots, secret check, and a clean-clone of `274866e`. Live framework export attempts 1–2 HTTP-succeeded but returned a source JD; attempt 3 used documented HTML export and semantic verification passed. Do not treat the GitHub PR as opened.

## Production hardening

- [x] Empty Phase-1 `backend/` and `frontend/` scaffolds removed (implementation lives in `src/` and `web/`)
- [x] Proven-unused Python helpers removed; SuperDocs `from_env` kept as a public constructor
- [x] Frontend consumes API metrics; corpus default is the first loaded corpus, not a hardcoded id
- [x] Reviewer UI visual polish (tokens, hierarchy, Change Impact as the primary change screen)
- [ ] Acceptance commit (not created in this session)
