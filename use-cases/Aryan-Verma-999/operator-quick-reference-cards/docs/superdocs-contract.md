# SuperDocs contract — M0

Contract source fetched 2026-08-15 from `https://docs.superdocs.app/llms-full.txt` and `https://docs.superdocs.app/openapi.json`. OpenAPI `info.version` is `2.0.0`. The source documents were inspected but are not copied into this project.

## Documented

| Concern | Current documented contract |
|---|---|
| Upload | `POST /v1/uploads` returns `upload_id` and a short-lived PUT URL; PUT bytes, then process. |
| Process | `POST /v1/uploads/{upload_id}/process` with `session_id`, `filename`, `parse_mode=document`, optional `return_html`; returns `version_id`, status, and possibly HTML. |
| Sessions | `POST /v1/sessions/init` can mint a session and open durable IDs; `POST /v1/sessions/{session_id}/documents/open` opens shared saved documents. |
| ID namespaces | Session roster documents expose `document_id` as a session-local slot and `durable_document_id` as the permanent document UUID. Chat accepts either. |
| Async edit | `POST /v1/chat/async` with `approval_mode=ask_every_time`, `document_id`, and `async_mode=true` returns `job_id`. This is the billable mutation. |
| Polling | `GET /v1/jobs/{job_id}` states include `pending`, `in_progress`, `awaiting_approval`, `completed`, `failed`, `cancelled`. Pending changes are in `metadata.pending_changes`. |
| Proposal shape | Documentation names `proposed_change_batch` in intermediate responses and `pending_changes` in polling metadata; change objects have chunk IDs and HTML diffs. |
| Approval | `POST /v1/chat/{session_id}/approve`: required `job_id`, required top-level `approved`, optional `change_id`/`feedback`, or `changes: [{change_id, approved, feedback}]`. |
| Read-back | `GET /v1/documents/{document_id}?include_html=true` returns saved detail, structure, and HTML. |
| Export | `POST /v1/documents/export` with `session_id` and `format=pdf`; response bytes are expected to be the exported file. |
| Usage | API-key usage is returned in chat/async responses and SSE `usage` events; `/v1/users/me/usage` is documented as web-session-only for this key type. |
| SSE | `GET /v1/chat/{session_id}/stream`; docs describe typed progress events, including `documents_changed`, `continue_prompt`, `model_fallback`, and `proposed_change_batch`. |

## Observed live

Live run completed 2026-08-15 using only the synthetic fixture. Credentials and full responses are intentionally omitted.

- `GET /v1/sessions` returned HTTP 200 (non-billable authentication check).
- `POST /v1/uploads`, signed PUT, and `POST /v1/uploads/{upload_id}/process` completed for the manual. The saved document list returned an object with `documents`; each entry used `document_id` (36-character UUID-shaped durable ID), `title`, and numeric `version`.
- `POST /v1/sessions/init` created an isolated task session. The session roster used `document_id` as an 11-character local slot (`doc_primary`) and `durable_document_id` as a distinct 36-character durable ID. The card and manual had different durable IDs.
- Processing a second editable upload after opening the manual reused the focused slot in this deployment. Creating the card first in an empty session and then `POST /v1/sessions/{session_id}/documents/open` for the manual produced the required distinct documents.
- `POST /v1/chat/async` targeted the card local slot with `approval_mode=ask_every_time`; the job reached `awaiting_approval`. Polling observed `pending`/processing progress and `proposed_change_batch` intermediate event types; `metadata.pending_changes` contained 3 object proposals with `change_id`, `chunk_id`, `document_id`, `old_html`, `new_html`, and `operation`.
- The first approval was mixed: one explicit rejection and two approvals. The job entered another approval round. A second explicit batch approval returned `batch_complete`; the job reached `completed`.
- `GET /v1/documents/{durable_document_id}` returned `html`, `version_id`, numeric `version`, and structure fields. The card HTML contained the exact specification and no placeholders. The manual durable ID/version remained separate and unchanged by targeting.
- `POST /v1/documents/export` returned HTTP 200, `content-type: application/pdf`, no warning headers, 18,524 bytes, SHA-256 `969cb69b999ab2ce766feb9ed987f808778b385e02c9921c7578bad9a1817a5e`, and a readable 1-page PDF.

The live edit consumed 1 operation. Usage counters were not present in the reconciled job payload; the API-key usage endpoint is documented as web-session-only, so account totals remain unresolved.

## Inferred / implementation guardrails

- Treat upload URLs, authorization, cookies, and raw response bodies as secret-bearing and never persist them.
- Treat every unknown mutating event as blocking.
- Normalize proposal values from polling and SSE defensively, including a possible second JSON parse, but record the original sanitized shape during a live run.
- Do not retry ambiguous billable mutations. Reconcile jobs/documents first.

## Still unknown after this live run

The exact signed-upload response fields were not persisted, SSE transport was not exercised, and this run did not require a nested JSON proposal string. Exact usage counters (`ops_charged`, `monthly_used`, `monthly_limit`, `quota_exhausted`) were absent from the observed async/job responses. The export is valid but intentionally only one page; M0 does not require the final two-page design.

## M1 implementation contract

M1 uses the observed shapes above as sanitized offline fixtures in `fixtures/m0-contract.json`. The document-list wrapper is normalized through its `documents` member; session-local `doc_primary` and durable UUID-shaped IDs are kept distinct; polling `metadata.pending_changes` and the `proposed_change_batch` intermediate event are intentionally separate decoders. The card is created first, then the manual is opened into the session, because a second editable upload can change the focused session slot.

The M1 live path must target only the card, use `approval_mode=ask_every_time`, preserve upstream proposal order and unique IDs, and continue until completion, failure, cancellation, contract violation, or the hard operation budget. Every proposal is checked against a copy of the exact local HTML before approval. A manual-target proposal, document creation/deletion, unsupported content, or any failed verifier invariant is ineligible.

M1 rough edges retained as reproducible integration findings: wrapper shape differs from simple-list assumptions; HTML uploads require `text/html`; one generation can require multiple approval rounds; focusing changes after a second editable upload; and API-key usage counters were not available from a separate account endpoint. No automatic bug report or external contact was made.

## Reconciliation diagnosis

The historical M1 observations in this section predate the corrected
`document_sync.content` parser. They explain prior implementation work but do
not determine the current provider conclusion; use
`docs/superdocs-live-bug-report.md` for the handoff-safe evidence.

The first M1 runner reached authoritative read-back but raised after a failed local verifier without persisting the returned HTML or structured report. This is a local integration observability defect (class J), not a confirmed SuperDocs product bug and not a reason to weaken verification. The run is recorded only as a sanitized diagnostic with unavailable check/value fields; no private response was copied. Future runs persist bounded hashes, versions, round counts, decisions, verifier checks, and card-block hashes before any failure is raised. A concise potential bug report is prepared but must remain unsent until a captured reproduction identifies whether the service or reconciliation logic is responsible.

The one controlled retry captured four approval rounds and authoritative read-back. All proposals were rejected; the unchanged authoritative/base hash still failed `PROTECTED_STRUCTURE` and `CITATION_PAGE_POINTERS` for `SPEC-001`, while source-locked value, safety, procedure, restart, numeric, and hostile-content checks passed. This is a confirmed local integration/skeleton contract discrepancy (class I), not yet a confirmed SuperDocs product bug: the returned HTML itself was not retained, only its sanitized hash and bounded block diff. Export correctly remained unattempted. No further live generation is authorized without deciding how to reconcile the upload/editor representation while preserving the hard verifier.

## M1.1 non-billable skeleton probe

Fresh-session Path A (`text/html` upload/process) and documented Path B (`documents/blank` followed by `documents/{document_id}/save` with `html`) were both tested without chat. Both retained visible exact content and page class names but stripped or rewrote doctype/body, page-break style, all `data-*` protection/evidence metadata, and the structured SPEC-001 citation span. Both failed the authoritative base gate on `PROTECTED_STRUCTURE` and `CITATION_PAGE_POINTERS`; neither was exported. The bounded comparison is stored under ignored `artifacts/m1/skeleton-probe.json`.

This is a confirmed direct-shell contract discrepancy, not a confirmed provider bug. M1.1 selects SuperDocs-reviewed content staging plus local deterministic placement with an immutable evidence sidecar. The direct runner blocks all billable chat when the authoritative base fails.

M1.2’s non-billable exact-HTML export probe passed HTTP 200 and a two-page PDF postflight. The earlier mapper issue is corrected: it now reads the documented `document_sync.content` HTML before reconciling proposal targets. A read-only recovery then found 8 synchronized chunks and 6 proposal targets with zero direct overlap; a fresh capped generation found 8 synchronized chunks and 31 proposal targets with zero overlap. No decision or export was submitted. This is a provider proposal-to-chunk correlation defect, not a local mapping defect.

## Contract status summary

### M4 image/export proof

One bounded non-AI image contract check is publicly summarized here. The
documented image-upload endpoint returned HTTP 200, the exact-HTML PDF export
returned HTTP 200, the returned PDF contained one embedded image and rendered
the locally generated SVG text, and no export warning header was observed. No
provider Mermaid HTML or `data-*` wire format was inferred or fabricated; the
provider-specific Mermaid representation remains unresolved.

**Documented:** pre-signed upload/process; blank/save endpoints; durable document read-back; exact-HTML export with `html` and `format=pdf`; asynchronous approval payloads.

**Observed live:** document-list `{documents,total}` wrapper; durable UUID-shaped IDs; session-local `doc_primary`; `metadata.pending_changes` objects; `proposed_change_batch`; top-level `approved` batch approvals; repeated rounds; separate manual/card identities; HTML MIME sensitivity; focused-slot replacement after a second editable upload; successful exact-HTML export.

**Inferred guardrails:** source content is untrusted; proposal targets require exact local identity; export follows authoritative read-back and local verification; ambiguous chunk-to-slot mapping is rejected.

**Unresolved:** provider delivery of a stable proposal-to-synchronized-chunk
correlation for arbitrary staging proposals; separate API-key usage counters.
The tested editable-document paths also normalize custom shell metadata and
print structure; that independent preservation limitation remains documented
without inferring an unsupported wire format.
