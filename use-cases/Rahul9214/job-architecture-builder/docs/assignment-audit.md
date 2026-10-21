# Task 2 assignment audit

Recorded against branch `task2-job-architecture-builder`, commit `274866eda8d266221853e79bff6862bfe653a9fc`, plus uncommitted Phase 9 documentation and a small production CSS contrast fix for `.chip.warn`.

Do not treat a row as PASS without the cited evidence. Live SuperDocs claims cite `docs/live-verification.md` only.

## Required outcomes

| Requirement | Implementation evidence | Verification evidence | File / test / UI | Status |
| --- | --- | --- | --- | --- |
| Existing job descriptions as input | Markdown JDs under `fixtures/corpus-a` and `fixtures/corpus-b`; parsed into `RoleEvidence` | Fixture schema tests; Sources page lists 21 Northstar / Meridian roles | `src/job_architecture/evidence.py`; `tests/test_fixtures.py`; `/sources` | PASS |
| Job families | Catalog families; corpus clusters labeled after grouping | Architecture metrics `proposed_families`; framework family cards | `src/job_architecture/family.py`; `catalog.py`; `/architecture`, `/framework` | PASS |
| Levels | Canonical IC1–IC5 and M1–M3 with occupied M2/M3 remaining in catalog | Framework tables show IC1–IC5 and M1–M3; management tests | `src/job_architecture/level.py`; `tests/test_management_levels.py`; `/framework` | PASS |
| Career tracks | IC vs people-manager from people-management evidence | EM Platform Services is `people_manager`; EM Developer Experience is IC | `src/job_architecture/track.py`; `tests/test_adversarial.py`; Architecture chips | PASS |
| Competency matrices | Per-family matrices on `FrameworkDocument`; evidence-limited flag when thin | Framework UI lists matrices per family | `src/job_architecture/framework.py`; `/framework` Competency matrices | PASS |
| Role profiles | Structured employee-readable profiles; misfits are review artifacts | Profiles API and UI; IC4 profile contains level expectations | `src/job_architecture/profiles.py`; `tests/test_web_acceptance.py`; `/profiles` | PASS |

## Required behaviors and evidence dimensions

| Requirement | Implementation evidence | Verification evidence | File / test / UI | Status |
| --- | --- | --- | --- | --- |
| 8. Evidence instead of title matching | Title excluded from clustering tokens and family scoring; family/track/level inferred from JD dimensions | Metamorphic title-swap tests keep family/track/level | `scoring.py`, `clustering`; `tests/test_adversarial.py::test_title_swap_does_not_change_family_track_level` | PASS |
| 9. Title / evidence conflict handling | Typed `TitleConflict` after evidence assignment; generic seniority / management / understatement rules | Dedicated tests for Workplace Tools, Payments, EM DX, EM Platform, Corpus B Principal | `src/job_architecture/assess.py`; `tests/test_title_conflict.py`; Architecture “Title vs evidence” | PASS |
| Evidence dimensions (scope, autonomy, complexity, impact, leadership, management, decision authority, stakeholders, domain, outcomes) | Copied from JD sections into `RoleEvidence`; UNSTATED when missing | Role drawer “Evidence signals”; extraction tests | `src/job_architecture/evidence.py`; `/architecture` drawer | PASS |
| 10. Honest provisional roles | Sparse, hybrid, and fit-changing title conflicts remain provisional | Program Coordinator sparse; Solutions Architect hybrid | `tests/test_adversarial.py`; `/exceptions` Provisional | PASS |
| 11. Honest misfits | Outside-architecture roles stay misfit with reasons; no auto-assign | Developer Advocate; Medical Science Liaison | `tests/test_adversarial.py`; `/exceptions` Misfit | PASS |
| 7. Defensible clustering | Field-weighted TF-IDF + occupational cosine, compatibility gate, title omitted; hybrids/sparse/misfits unclustered or bridges | Clustering tests; Architecture “Craft neighborhoods” | `tests/test_clustering.py`; `/architecture` | PASS |

## SuperDocs surfaces (A5)

| Requirement | Implementation evidence | Verification evidence | File / test / UI | Status |
| --- | --- | --- | --- | --- |
| 12. Multi-document | Upload with `open_mode=new_focused`; session roster | Live record: four JD document ids coexisted | `src/job_architecture/superdocs/client.py`; `docs/live-verification.md` roster | PASS |
| 13. Search | Async chat with `cross_session_search=true`; resume polls same job id | Live resume: 0 extra mutating calls, no second POST, `completed`, `verified/terminal/has_result=true` | `scripts/superdocs_live.py`; live-verification Search row | PASS |
| 14. Templates | Template upload-base64 for framework and role-profile | Live record: two templates uploaded | live-verification templates row; `templates/*.md` | PASS |
| 15. Review | `approval_mode=ask_every_time`; per-change approve/reject | Framework/profile/repair approved; surgical 1–2 rejected; attempt 3 approved | live-verification decision log; `/review` for local plans | PASS |
| 16. Export | `POST /v1/documents/export` with documented `html` + `session_id` + `format` + `filename`; local DOCX also from web | Live profile DOCX export succeeded; live framework attempts 1–2 HTTP-succeeded but returned a source JD; attempt 3 HTML export semantic PASS | live-verification `export --kind profile` PASS; `export --kind framework` attempt 3 **PASS** (attempts 1–2 kept as failed evidence); `/export` | PASS |

## Surgical propagation (A3) and human gate (A4)

| Requirement | Implementation evidence | Verification evidence | File / test / UI | Status |
| --- | --- | --- | --- | --- |
| 17. Changed level definition | `analyze_level_change` / web impact | Offline acceptance plans an IC4 scope change | `src/job_architecture/impact.py`; `/impact`; `tests/test_web_acceptance.py` | PASS |
| 18. Dependent-profile detection | Explicit `DependencyEdge` level → `level_expectations` | Impact payload affected vs unaffected counts | `src/job_architecture/graph.py`; `/impact` | PASS |
| 19. Surgical updates | Patch only changed canonical dimensions | Live attempt 3: version + Scope only; attempt 1 rejected for Complexity spill | `plan_level_updates`; live-verification surgical 3 | PASS |
| 20. Preservation of unrelated content | SHA-256 section hashes; `PreservationReport.violations` fail | Live `verify-export` passed; offline apply keeps purpose | `tests/test_framework_propagation.py`; live-verification preservation | PASS |
| 21. Explicit human approval/rejection | No auto-approve; CLI `--confirm`; web Approve/Reject | Decision log; review UI | `scripts/superdocs_live.py`; `/review` | PASS |
| 22. Rejected change remains unapplied | `review_outcome=rejected`, `mutation_applied=false` even if remote `completed` | Surgical attempts 1–2 kept in history; versions not advanced | `tests/test_live_review_resume.py`; live-verification | PASS |
| Domain apply only after verification | `finalize-domain` local; remote `completed` is not apply | Live finalize after structure + preservation | `tests/test_live_domain_apply.py`; live-verification | PASS |

## Production engineering (A6)

| Requirement | Implementation evidence | Verification evidence | File / test / UI | Status |
| --- | --- | --- | --- | --- |
| 23. Second-corpus validation | Same engine on Meridian fixtures | `tests/test_web_acceptance.py::test_corpus_b_smoke_path`; Corpus B UI uses `/api/*/{corpus_id}` | fixtures/corpus-b; `/` organization select | PASS |
| 24. Offline tests | pytest MockTransport; Vitest mocked fetch | pytest and `npm test` without a live key | `tests/`; `web/src/test/` | PASS |
| 25. Actionable failure handling | Typed SuperDocs errors; UI `role="alert"` messages | Client tests for timeout/5xx; Export/Review error banners | `src/job_architecture/superdocs/`; Status.tsx | PASS |
| 26. Retries / resume / idempotency | Safe GET retry; no blind POST retry; `operation_key`; Search resume same job | Documented in README; live Search resume 0 extra POSTs | `client.py`; live-verification Search | PASS |
| 27. Secret hygiene | `.env` gitignored; runtime state refuses secret keys; API status redacts | `docs/security-check.md`; `tests/test_web_api.py` secret markers | `.gitignore`; `live/state.py` | PASS |
| 28. Clean-clone reproducibility | README install from a fresh clone of this branch | `docs/clean-clone-verification.md` | temp clone under `%TEMP%` | PASS |
| 29. Reviewer-facing documentation | README + TASK2 + this audit + live/manual/security/clone docs | Files in `docs/` and README | README.md; docs/* | PASS |

## Acceptance criteria summary

| ID | Criterion | Status |
| --- | --- | --- |
| A1 | Defensible architecture with exposed reasoning | PASS — supporting/counter evidence and source locators |
| A2 | Honest misfits / provisional | PASS |
| A3 | Surgical propagation + preservation | PASS (offline + live profile path) |
| A4 | Human gate | PASS |
| A5 | SuperDocs upload, multi-document, search, templates, review, export | PASS — framework reviewed edit proven; framework export attempt 3 HTML semantic PASS (attempts 1–2 failed with a source JD and are retained as evidence) |
| A6 | Production engineering | PASS |

## Non-goals (NOT APPLICABLE)

HRIS, ATS, compensation benchmarking, salary bands, employee-record management, auth/RBAC, generic document editing, generic chatbot, real private HR data, automatic approval, automatic publication — none implemented; none required.

## Task-2 requirement map (A–AO)

Recorded against the working tree of this release-candidate pass. Live SuperDocs claims cite `docs/live-verification.md` only.

| ID | Requirement | Implementation | Test / evidence | UI surface | Live SuperDocs | Status |
| --- | --- | --- | --- | --- | --- | --- |
| A | Synthetic JDs | Markdown JDs under `fixtures/` | `tests/test_fixtures.py` | `/sources` | Demo subset uploaded | PASS |
| B | Job families | Catalog + post-cluster labels | architecture metrics; family tests | `/architecture`, `/framework` | Framework HTML contains families | PASS |
| C | Career tracks | IC vs people-manager from evidence | `tests/test_adversarial.py` | Architecture chips | Framework tracks in export | PASS |
| D | Levelling framework | Canonical IC1–IC5, M1–M3 | `tests/test_management_levels.py` | `/framework` | Framework export attempt 3 | PASS |
| E | Competency matrices | Per-family matrices; evidence-limited flag | framework tests | `/framework` Competency matrices | Included in HTML export | PASS |
| F | Role profiles | Employee-readable profiles; misfits as artifacts | `tests/test_web_acceptance.py` | `/profiles` | Live profile DOCX | PASS |
| G | Evidence over title | Title excluded from clustering/family scoring | title-swap metamorphic test | Architecture lede + drawer | N/A (domain) | PASS |
| H | Senior title / narrow scope | Typed `title_conflict` after evidence assignment | `tests/test_title_conflict.py` Workplace Tools | Title vs evidence | N/A | PASS |
| I | Modest title / broad scope | Same typed conflict path | Payments IC4 case | Title vs evidence | Surgical target | PASS |
| J | Manager title / no management | Management-title mismatch vs genuine EM | EM DX vs EM Platform tests | Title vs evidence | N/A | PASS |
| K | Hybrids | Bridge, not forced family | hybrid unclustered tests | `/exceptions` Hybrid | N/A | PASS |
| L | Sparse roles | Remain provisional | Program Coordinator tests | `/exceptions` Provisional | Demo subset | PASS |
| M | Misfits / out-of-architecture | Stay misfit; no auto-assign | Developer Advocate / MSL tests | `/exceptions` Misfit | N/A | PASS |
| N | Confidence / fit semantics | Coarse buckets; fit chips | assess + UI chips | Architecture, Exceptions | N/A | PASS |
| O | Clustering | TF-IDF + occupational cosine, compatibility gate | `tests/test_clustering.py` | Craft neighborhoods | N/A | PASS |
| P | Clustering not family-id grouping | Labels applied after grouping | architecture tests forbid fixture-id grouping | `/architecture` | N/A | PASS |
| Q | Second corpus | Same engine on Meridian fixtures | `test_corpus_b_smoke_path` | Organization select | N/A | PASS |
| R | No corpus/role hardcoding | Production `src/` has no Northstar/Meridian/`ns-`/`mh-` branches | fixture-id scan | Frontend consumes API | N/A | PASS |
| S | M1–M3 completeness | Catalog keeps unoccupied M2/M3 | framework tables | `/framework` | Attempt 3 HTML | PASS |
| T | Dependencies | Explicit `DependencyEdge` level → `level_expectations` | graph tests | `/impact` dependency path | Surgical 3 | PASS |
| U | Impact analysis | Occupied level + dimension OLD/NEW | `tests/test_web_acceptance.py` | `/impact` | N/A (local planner) | PASS |
| V | Surgical propagation | Patch only changed canonical dimensions | planner tests; live attempt 3 | `/impact` plans | Attempt 3 version + Scope | PASS |
| W | Unaffected preservation | SHA-256 section hashes | `tests/test_framework_propagation.py` | Impact preservation copy | `verify-export` PASS | PASS |
| X | Human review | No auto-approve; Approve/Reject | review API tests | `/review` | `ask_every_time` | PASS |
| Y | Mixed approve/reject | Per-plan decisions | review tests | `/review` | Surgical 1–2 reject, 3 approve | PASS |
| Z | Idempotency | Safe GET retry; no blind POST retry; `operation_key` | live resume tests | N/A | Search 0 extra POSTs | PASS |
| AA | Multi-document | `open_mode=new_focused`; roster | client tests | Evidence dialog status | Four JD ids coexisted | PASS |
| AB | Search | Async chat `cross_session_search=true` | live-verification Search row | N/A (CLI) | Resume verified/terminal/has_result | PASS |
| AC | Templates | Framework and role-profile template upload | live-verification templates | N/A (CLI) | Two templates uploaded | PASS |
| AD | Review | SuperDocs review + local web review | `/review`; live decision log | `/review` | Framework/profile/repair/surgical | PASS |
| AE | Export | Local web DOCX + live CLI export | web export API tests | `/export` | Profile DOCX; framework attempt 3 | PASS |
| AF | Profile DOCX live proof | Live `export --kind profile` | live-verification | N/A (CLI) | PASS after repair + surgical 3 | PASS |
| AG | Framework DOCX live proof | HTML + `session_id` export | live-verification attempts 1–3 | N/A (CLI) | Attempt 3 PASS; 1–2 retained FAIL | PASS |
| AH | Live search proof | Resume same job id | live-verification Search | N/A (CLI) | PASS | PASS |
| AI | Rejected attempts preserved | History keeps rejected jobs | `tests/test_live_review_resume.py` | Review state | Attempts 1–2 retained | PASS |
| AJ | No auto approval | `--confirm`; web Approve/Reject | review tests | `/review` | `ask_every_time` | PASS |
| AK | Offline usability | pytest MockTransport; UI without key | pytest; vitest | Full reviewer path | N/A | PASS |
| AL | Reviewer UI | FastAPI + React workspace | vitest + manual acceptance | All primary routes | Status only; no live export button that works | PASS |
| AM | Responsive / accessibility | 44px controls; combobox; drawers; collapsed tooltips | vitest; Lighthouse a11y | Shell + pages | N/A | PASS |
| AN | Clean clone | README install without `.runtime` or key | `docs/clean-clone-verification.md` | SPA after `npm run build` | N/A | PASS at `274866e`; re-run after this uncommitted pass is committed |
| AO | Secret hygiene | gitignore; redaction; runtime refusal | `docs/security-check.md`; API tests | Export never shows the key | Key never copied into git | PASS |

AN is PASS for the last cloned commit. This uncommitted UI pass is not in that clone until a later commit.

## Hosted deployment


NOT APPLICABLE. No hosted SuperDocs or public deployment is claimed. Reviewer UI is local FastAPI.
