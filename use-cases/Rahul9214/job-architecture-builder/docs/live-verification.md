# Live SuperDocs verification record

Template for the human-run Phase 7A live path. Do not invent values. Leave unexecuted rows as `not run`.

Never paste `SUPERDOCS_API_KEY` or other credentials here.

## Session

| Field | Value |
| --- | --- |
| Date | 2026-08-25 (upload through first surgical review); 2026-08-26 (repair, surgical attempts 2–3, profile export, search, local domain-apply, framework export attempts 1–3) |
| Operator | human |
| Environment (`SUPERDOCS_BASE_URL`) | not recorded here |
| Local session id | `job-arch-live` |
| SuperDocs session id (if different) | not copied into git |
| Runtime state file | `.runtime/live-state.json` |
| Notes | Multi-document upload and templates passed. Framework and profile reviewed edits were approved. The original profile fill duplicated Level expectations; in-place repair was approved. Surgical attempt 1 was rejected (unrelated Complexity rewrite). Surgical attempt 2 was rejected (duplicated live baseline). Surgical attempt 3 was approved (version + Scope only). Review prevented the incorrect changes. Rejected attempts remain in history. Search was resumed on the same job id (estimated mutating SuperDocs calls: 0; no second POST `/v1/chat/async`). Remote status reached `completed`. Recorded `verified=true`, `terminal=true`, `has_result=true`. Framework export attempts 1–2 HTTP-succeeded but returned a source JD. Attempt 3 used documented HTML + `session_id` export (15,650 chars of deterministic framework HTML); semantic verification **passed**. Do not copy live document or job ids into git. |

## Demo subset

Corpus A roles (synthetic):

- `ns-swe-backend` — typical engineering IC
- `ns-swe-ii-payments` — broader/higher-scope engineering IC (surgical target)
- `ns-em-platform` — people manager
- `ns-program-coordinator` — sparse/provisional

Search query: `Find documents or role profiles that reference the IC4 level.`

## Operations

| Operation | Status | Document / session / job ids (non-secret) | Elapsed | Final status | Proposed-change count | Decisions | Export result | Preservation result |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `prepare` (local DOCX only) | succeeded (local) | generated under `artifacts/live/` | not recorded | local write; filled profile has exactly one Level expectations block | | | | |
| `upload` (4 JDs + 2 templates) | succeeded | session `job-arch-live`; four distinct JD `document_id`s; framework and profile documents uploaded | not recorded | roster ok; durables now present in `.runtime/` | | | | |
| roster / multi-document check | succeeded | four coexisting JD documents; distinct session `document_id`s | not recorded | **passed** | | | | |
| templates | succeeded | framework and role-profile templates uploaded | not recorded | **passed** | | | | |
| `framework` reviewed edit | succeeded | live job id not copied into git | not recorded | completed after human approve | not recorded | **approved** | | |
| `decide --job framework` | succeeded | | not recorded | remote completed; mutation applied candidate | not recorded | approve | | |
| `profile` (SuperDocs fill against already-filled DOCX) | succeeded as a job; produced a malformed live baseline | live job id not copied into git | not recorded | remote completed after human approve; live Level expectations duplicated | not recorded | **approved** | | duplicated dimensions then in the live document |
| `decide --job profile` | approved | | not recorded | remote completed; `mutation_applied=true` for the fill; structural result was duplicated dimensions | not recorded | approve | | |
| `surgical-update` (attempt 1) | submitted; reached human review; **rejected** | live job id not copied into git | not recorded | remote `completed`; review rejected; mutation not applied | 1 | **rejected — unrelated Complexity rewrite** | not exported | planner semantic spill |
| `decide --job surgical` (attempt 1) | rejected | human rejected the Complexity rewrite | not recorded | `review_outcome=rejected`; `mutation_applied=false`; `domain_applied=false` | 1 | reject | | versions not advanced |
| `surgical-update` (attempt 2, planner-corrected) | submitted; reached human review; **rejected** | live job id not copied into git | not recorded | remote `completed`; review rejected; mutation not applied | 1 | **rejected — malformed duplicated baseline** | not exported | BEFORE already showed duplicated Level expectations |
| `decide --job surgical` (attempt 2) | rejected | human rejected applying a correct scope patch onto a duplicated baseline | not recorded | `review_outcome=rejected`; `mutation_applied=false`; `domain_applied=false` | 1 | reject | | versions not advanced |
| local planner bug | discovered after attempt 1 | `plan_level_updates` re-rendered full `level_expectations` | | fixed offline | | | | |
| local resume bug | discovered after attempt 1 | completed rejected job treated as success | | fixed offline; rejected attempts remain in history | | | | |
| local profile-baseline bug | discovered after attempt 2 | SuperDocs fill replaced a too-narrow header span on an already-filled profile | | fixed offline: upload filled profile as source of truth; do not SuperDocs-fill it | | | | |
| `repair-profile` (in-place duplicate removal) | succeeded | live job id not copied into git | not recorded | remote completed after human approve; mutation applied on the existing profile lineage | not recorded | **approved** | | |
| `export --kind profile` after repair | succeeded | wrote `exports/profile.docx` | not recorded | **passed** | | | succeeded | |
| `verify-profile-structure` (repair-era export) | initial run failed on paragraph-based field boundaries; corrected verifier then **passed** | existing `exports/profile.docx` at that time (file later re-exported after surgical 3) | | repair-era: section count 1; SuperDocs stored Level expectations as one paragraph / multiple runs / `w:br` | | | | |
| `surgical-update` (attempt 3) | submitted; reached human review; **approved** | live job id not copied into git | not recorded | remote `completed`; `review_outcome=approved`; `mutation_applied=true`; `domain_applied` not inferred from completed | 1 | **approved — version + Scope only** | | |
| `decide --job surgical` (attempt 3) | approved | human approved version + Scope only | not recorded | `review_outcome=approved`; `mutation_applied=true`; `domain_applied=false` until verification-gated finalize | 1 | approve | | |
| `export --kind profile` after surgical 3 | succeeded | wrote `exports/profile.docx` | not recorded | **passed** | | | succeeded | |
| repaired/exported profile structure | **passed** | checked `exports/profile.docx` | | semantic structure PASS; Level expectations section count = 1; header = IC4 definition version 2; no structural violations | | | | |
| `verify-export` preservation | **passed** | checked `exports/profile.docx` | | new sequencing-veto fragment found; purpose preserved; responsibilities preserved; autonomy/complexity/impact/leadership/people_management unchanged (complexity: `Matches the published complexity of this level.`) | | | | **passed** with those observed checks |
| `finalize-domain` | succeeded (local) | no SuperDocs call | | `domain_applied=true`; dependency/source version 1 → 2; idempotent re-run keeps version 2; rejected attempts remain in history (2) | | | | |
| `search` | resumed same job; remote **completed**; verified | live job id not copied into git | not recorded | `verified=true`; `terminal=true`; `has_result=true`. Estimated mutating SuperDocs calls: 0. No second POST `/v1/chat/async`. Search-result body is not copied into git. | | | | |
| `export --kind framework` attempt 1 | HTTP succeeded; **semantic verification FAILED** | SuperDocs returned a DOCX to `exports/framework.docx` | not recorded | file written | | | **wrong document** — extracted text is a source JD (`Software Engineer, Backend` / Platform Services), not the framework | **NOT VERIFIED** |
| `export --kind framework` attempt 2 | HTTP succeeded; **semantic verification FAILED** | Correct local semantic `document_id` / `durable_document_id` were supplied; SuperDocs still returned the source JD | not recorded | file written | | | **wrong document** — those fields are not part of the documented export selection contract | **NOT VERIFIED** |
| `export --kind framework` attempt 3 | HTTP succeeded; **semantic verification PASS** | Documented HTML + `session_id` contract; 15,650 chars of deterministic framework HTML; wrote `exports/framework.docx` | not recorded | **passed** | | | **passed** — purpose, principles, Individual Contributor, People Manager, IC1–IC5, M1–M3, job_family; missing none; `looks_like_source_jd=false` | **passed** |
| `verify-framework-structure` after attempt 3 | **passed** (local) | checked `exports/framework.docx` | | `semantic ok=True`; excerpt starts `Job architecture — Northstar Systems` / Purpose / Canonical job architecture… / Principles / Titles never determine family, track, or level | | | | **passed** |

Current SuperDocs docs (`https://docs.superdocs.app/llms-full.txt`, POST `/v1/documents/export`): the body is `{ html?, session_id?, upload_id?, format, options?, filename? }`. One of `html` / `session_id` / `upload_id` is required. There is **no** `document_id` or `durable_document_id` field. Sending only `session_id` exports the session's current/default document.

Attempt 1 sent `session_id` + output filename and got the first JD.
Attempt 2 also sent session `document_id` and `durable_document_id` (undocumented). SuperDocs ignored them and still returned the source JD.
Attempt 3 POSTed non-empty deterministic HTML from `render_framework_html(FrameworkDocument)` with `session_id`, `format=docx`, and `filename` / `options.filename` (15,650 chars). Automatic semantic verification PASS; explicit `verify-framework-structure` reported `semantic ok=True`. Domain data is the source of truth. File existence alone is not success; attempts 1–2 wrote a file and still failed. Do not require DOCX package byte identity. Framework reviewed edit and framework **export attempt 3** are both proven.

## Multi-document roster

| Check | Result |
| --- | --- |
| Distinct document ids | **passed** (live roster) |
| All four JD uploads present | **passed** (live roster) |
| Durable ids present on roster | **passed** (live roster) |
| Durable ids persisted in `.runtime/` | failed on first run (`null`); later repaired in local state without copying ids into git |
| Framework starter id | present in `.runtime/` (not copied into git) |
| Profile document id | present in `.runtime/` (not copied into git); same lineage kept for in-place repair and surgical 3 |

## Surgical preservation

Do not claim byte identity of DOCX container files. SuperDocs may rewrite package metadata.

| Check | Result |
| --- | --- |
| Local filled profile structure | **valid** (exactly one of each Level expectations field) |
| Live SuperDocs profile structure after original fill | **invalid** (dimensions duplicated) |
| Live SuperDocs profile after repair + surgical 3 export | **passed**: one Level expectations section; header IC4 definition version 2; Scope contains the approved sequencing-veto addition |
| Autonomy unchanged | **passed** |
| Complexity unchanged | **passed** (`Matches the published complexity of this level.`) |
| Impact unchanged | **passed** |
| Leadership unchanged | **passed** |
| People-management unchanged | **passed** |
| New fragment present | **passed** (preservation verifier found the sequencing-veto addition) |
| Purpose preserved | **passed** |
| Responsibilities preserved | **passed** |
| Surgical attempt 1 | **rejected** — unrelated Complexity rewrite. Review prevented the incorrect change. |
| Surgical attempt 2 | **rejected** — malformed duplicated baseline. Review prevented the incorrect change. |
| Surgical attempt 3 | **approved** — version + Scope only. `mutation_applied=true`. Local `finalize-domain` then set `domain_applied=true` and advanced IC4 1 → 2 after structure + preservation verification. |
| Rejected attempts in history | **kept** (attempt 1 and attempt 2) |

## Observed SuperDocs bugs / rough edges

| Observation | Impact | Workaround |
| --- | --- | --- |
| Upload POST / focused document ref can omit `durable_document_id` while `GET /v1/sessions/{id}/documents` returns it | `.runtime/live-state.json` stored null durable ids even though the CLI printed roster durables | After roster verification, reconcile persisted documents by `document_id`. Re-run `upload` to repair; do not re-upload completed JDs. Never replace a known durable id with null. |
| SuperDocs proposed the full local AFTER block, including an unrelated Complexity rewrite | First surgical review had to be rejected | Local bug: `plan_level_updates` fully re-rendered `level_expectations`. Fixed to patch only changed canonical dimensions. |
| SuperDocs reports `status=completed` after a rejected review | Remote execution finished, but mutation was not applied | Persist `review_outcome` and `mutation_applied` separately from `remote_job_status`. `domain_applied` stays false until verification-gated finalize. |
| SuperDocs `replace_span` can target only the Level expectations header/`IC4 (definition version 1)` line and insert the full block above the existing dimension lines | Live profile had each canonical dimension twice | Do not SuperDocs-fill an already-filled profile. Repair in place, then surgical-update only on a verified unique block. |
| SuperDocs exported Level expectations as one paragraph with multiple runs and `w:br` | First structural verifier treated layout as missing fields | Parse canonical markers, not Word paragraph boundaries. |
| Search job can remain in processing after submit | Submit is not a terminal result | Resume polled the same job id (no second POST). Later poll reached `completed` with `verified=true`, `terminal=true`, `has_result=true`. |
| SuperDocs `POST /v1/documents/export` with only `session_id` (or undocumented document ids) returns the session current/default document | Live framework export attempts 1–2 HTTP-succeeded but wrote a source JD (`Software Engineer, Backend`) | Attempt 3 sent documented non-empty `html` plus `session_id` / `format` / `filename`. Semantic verification passed. Do not treat file existence as verification. |

## Decision log

| Job | Change id | Approve / reject | Timestamp |
| --- | --- | --- | --- |
| framework | (live change id not copied into git) | approve | 2026-08-25 |
| profile fill | (live change id not copied into git) | approve | 2026-08-25 |
| surgical (attempt 1, unrelated Complexity rewrite) | (live change id not copied into git) | reject | 2026-08-25 |
| surgical (attempt 2, malformed duplicated baseline) | (live change id not copied into git) | reject | 2026-08-26 |
| profile_repair (remove duplicate Level expectations) | (live change id not copied into git) | approve | 2026-08-26 |
| surgical (attempt 3, version + Scope only) | (live change id not copied into git) | approve | 2026-08-26 |
