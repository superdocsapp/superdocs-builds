# Behaviour ledger

Every behaviour this mock reproduces and this contract suite asserts, one row each, with the
source it came from. **Every test in `contract/` names the `B-ID` it covers**, and CI fails if
any row here has no test. The ledger is the specification of the mock; the mock is not the
specification of the ledger.

Written before any code, deliberately: name what the system must never do, then the test that
proves it, then the code.

**Transport** — `R` REST · `M` MCP · `B` both.

**Status** — `spec` derived from the pinned `openapi.json` · `docs` from a prose docs page ·
`live` confirmed against `api.superdocs.app` · `DRIFT` live behaviour diverges from the
published surface, see [findings.md](findings.md) · `VERIFY` sources disagree and the live
service has not settled it yet.

A `DRIFT` row is still implemented by the mock **as the live service behaves**, not as the
document says. The mock's job is to be a faithful double; the finding is where the
disagreement gets reported.

Sources are docs.superdocs.app paths unless noted. `openapi@ac0d44c` is the pinned spec.

---

## Authentication

| ID | T | Behaviour | Source | Status |
|---|---|---|---|---|
| B-001 | B | Auth is `Authorization: Bearer <key>`; personal keys are `sk_…`, organization keys `lce_…` | `/introduction/quickstart`, `openapi@ac0d44c` HTTPBearer | spec |
| B-002 | R | A malformed header returns `401` with `detail: "Invalid authorization header format. Expected 'Bearer <api_key>'"` | `/errors/error-codes` | docs |
| B-003 | R | An unknown or revoked key returns `401` with `detail: "Invalid API key"` | `/errors/error-codes` | docs |
| B-004 | R | SSE cannot carry headers, so `/v1/chat/{sid}/stream` authenticates via the `api_key` query parameter | `/guides/streaming` | docs |
| B-005 | R | `/v1/users/me/usage` and `/v1/users/me/limits` are web-app-only and reject `sk_`/`lce_` keys with `401` | `/errors/rate-limits` | **live** |
| B-006 | M | The MCP endpoint uses the **same** bearer token as REST — no separate MCP credential exists | `/mcp/setup` | docs |
| B-007 | M | A `401` from the MCP `health` tool means the key is wrong, not that the service is down; `GET /health` over REST is the zero-auth probe | `/mcp/setup` | docs |

## Sessions

| ID | T | Behaviour | Source | Status |
|---|---|---|---|---|
| B-008 | B | `session_id` is chosen by the client. There is no create-session call; first use of a string starts that session | `/introduction/quickstart`, `/concepts/sessions` | docs |
| B-009 | B | `session_id` must match `^[a-zA-Z0-9_\-\.]+$`, max 256 chars; violations return `422` `string_pattern_mismatch` | `openapi@ac0d44c` UniversalChatRequest, `/errors/error-codes` | spec |
| B-010 | B | The server holds the document between turns — `document_html` is omitted on every turn after the first | `/concepts/documents` | docs |
| B-011 | B | Sending `document_html` again **replaces** the server's copy wholesale, as a verbatim load; the AI never re-types content passed this way | `openapi@ac0d44c` UniversalChatRequest, `/concepts/documents` | spec |
| B-012 | R | Revert returns `409` while a chat job on the same session is `pending`, `in_progress` or `awaiting_approval` | `/guides/async-jobs`, `/errors/error-codes` | docs |
| B-013 | R | A revert target predating the feature returns `422`, not `404` | `/errors/error-codes` | docs |

## Chat and response shape

| ID | T | Behaviour | Source | Status |
|---|---|---|---|---|
| B-014 | B | `ChatResponse` always carries `response` and `session_id`; both are required | `openapi@ac0d44c` ChatResponse | spec |
| B-015 | B | `document_changes` is present **only** when the document actually changed | `openapi@ac0d44c` ChatResponse | spec |
| B-016 | B | `response_mode: "full"` (default) returns `document_changes.updated_html`; `"compact"` sets it to `null` and returns per-section `chunk_diffs` instead | `openapi@ac0d44c` UniversalChatRequest + DocumentChanges | spec |
| B-017 | B | Returned document HTML carries `data-chunk-id` attributes; the same ids appear as `chunk_id` / `insert_after_chunk_id` in proposed changes | `/concepts/documents` | docs |
| B-018 | B | `usage.ops_charged` may exceed 1 — one operation per 25 sections edited — so `monthly_used` can jump by more than one between responses | `openapi@ac0d44c` UsageInfo | spec |
| B-019 | B | `usage.quota_exhausted` true means the current request still completes; further billable requests pause | `openapi@ac0d44c` UsageInfo | spec |
| B-020 | B | `usage.bucket_used` is `"tier"` or `"promo"`, and `null` for non-billable operations | `openapi@ac0d44c` UsageInfo | spec |
| B-021 | R | `hint` is advisory and absent from most responses; `prefer_chat_async_for_large_generations` is the documented value | `openapi@ac0d44c` ChatResponse | spec |
| B-022 | B | `model_tier` ∈ `core` (default), `turbo`, `pro`, `max`; `thinking_depth` ∈ `fast`, `balanced` (default), `deep` | `openapi@ac0d44c` UniversalChatRequest | spec |
| B-023 | B | `approval_mode` ∈ `approve_all` (default, auto-applies) and `ask_every_time` (pauses for review) | `openapi@ac0d44c` UniversalChatRequest | spec |
| B-024 | B | HITL requires the async endpoint — the job has to pause, which a synchronous call cannot do | `/guides/human-in-the-loop` | docs |

## Async jobs

| ID | T | Behaviour | Source | Status |
|---|---|---|---|---|
| B-025 | B | `POST /v1/chat/async` returns `job_id`, `session_id` and `status: "pending"` | `openapi@ac0d44c` AsyncChatResponse | spec |
| B-026 | B | Job statuses are `pending`, `in_progress`, `awaiting_approval`, `completed`, `failed`, `cancelled` | `openapi@ac0d44c` JobResponse | spec |
| B-027 | B | `job_id` is an opaque UUID string; chat and attachment jobs share one id space and one `GET /v1/jobs/{id}` path | `/guides/async-jobs` | docs |
| B-028 | B | `job_type` ∈ `chat`, `attachment_processing`, `large_export` | `/guides/async-jobs` | docs |
| B-029 | B | `result` is present only on `completed`; `error` only on `failed` | `openapi@ac0d44c` JobResponse | spec |
| B-030 | B | Only `pending` and `in_progress` jobs can be cancelled | `/guides/async-jobs` | docs |
| B-031 | B | **All** jobs are purged 1 hour after creation, including those sitting in `awaiting_approval`; afterwards `GET /v1/jobs/{id}` is `404 "Job not found"` | `/guides/async-jobs`, `/errors/error-codes` | docs |
| B-032 | B | Unattended reviews are auto-denied by the server after roughly an hour | `/guides/human-in-the-loop` | docs |

## The two flavours of `awaiting_approval`

| ID | T | Behaviour | Source | Status |
|---|---|---|---|---|
| B-033 | B | `metadata.awaiting_kind` disambiguates the pause. `"continue_prompt"` → a large edit paused; anything else → a HITL change review | `/guides/human-in-the-loop`, `/guides/async-jobs` | docs |
| B-034 | B | A `continue_prompt` pause carries `metadata.continue_prompt` = `{message, done, total, remaining}` and **no** `pending_changes` | `/guides/async-jobs` | docs |
| B-035 | B | A `continue_prompt` pause is resolved with `/continue` (`continue_chat`), never `/approve` | `/guides/async-jobs` | docs |
| B-036 | B | Calling `/approve` on a `continue_prompt` pause returns `409` — and the converse likewise | `/guides/human-in-the-loop` | docs |
| B-037 | B | `continue: true` resumes with a fresh budget; `continue: false` stops and **keeps** the work already applied | `openapi@ac0d44c` ContinueRequest | spec |
| B-038 | B | A resumed job may pause again for the next segment — continue prompts loop | `/guides/async-jobs` | docs |
| B-039 | B | A continue pause can occur in **either** approval mode | `/guides/async-jobs` | docs |

## Human-in-the-loop approval

| ID | T | Behaviour | Source | Status |
|---|---|---|---|---|
| B-040 | B | `metadata.pending_changes[]` carries the proposals while a job awaits review | `openapi@ac0d44c` JobMetadata | spec |
| B-041 | B | Top-level `approved` is **required on every approve request, including batch shapes**; omitting it returns `422` | `/guides/human-in-the-loop`, `openapi@ac0d44c` ApprovalRequest | spec |
| B-042 | B | Three valid shapes: single (`change_id`+`approved`), batch-uniform (`approved`+`changes[{change_id}]`), batch-per-change (`approved`+`changes[{change_id, approved}]`) | `/guides/human-in-the-loop` | docs |
| B-043 | B | Top-level `approved` is the default for any entry in `changes` that omits its own | `/guides/human-in-the-loop` | docs |
| B-044 | B | `PendingChange` requires `change_id` and `operation`; `operation` ∈ `edit`, `create`, `delete` | `openapi@ac0d44c` PendingChange | spec |
| B-045 | B | Field nullability follows the operation: `edit` has both htmls; `create` has `new_html` + `insert_after_chunk_id`, `old_html` null; `delete` has `old_html`, `new_html` null | `/guides/human-in-the-loop` | docs |
| B-046 | B | Every change in a batch carries `batch_id` (equal to the first change's `change_id`) and `batch_total` | `/guides/human-in-the-loop` | docs |
| B-047 | B | In multi-document sessions every change carries the `document_id` it belongs to | `openapi@ac0d44c` PendingChange | spec |
| B-048 | B | Denying with feedback can produce a further `awaiting_approval` round — the loop is not single-shot | `/guides/human-in-the-loop` | docs |
| B-049 | B | `metadata.pending_batch_decisions` maps already-decided `change_id`s to their decision, so a reloaded client renders only the remainder | `/guides/human-in-the-loop` | docs |
| B-050 | B | Header, footer, footnote, endnote and comment edits arrive as ordinary entries in the same batch — there is no separate approval track | `/guides/human-in-the-loop` | docs |

## SSE streaming

| ID | T | Behaviour | Source | Status |
|---|---|---|---|---|
| B-051 | R | Exactly nine event types: `intermediate`, `proposed_change_batch`, `document_sync`, `continue_prompt`, `documents_changed`, `model_fallback`, `final`, `usage`, `error` | `/guides/streaming` | docs |
| B-052 | R | **`proposed_change_batch.content` is a JSON-encoded string requiring a second parse**, while `final.result` is already an object after one parse | `/guides/streaming` | docs |
| B-053 | R | Every HITL turn arrives as a single `proposed_change_batch` carrying a `changes` array — one change or hundreds | `/guides/streaming` | docs |
| B-054 | R | A one-change turn uses `type: "single_approval"`; multi-change uses `"batch_approval"`. A standalone `proposed_change` event **never fires** | `/guides/streaming` | docs |
| B-055 | R | Every event carries a monotonically increasing `sequence` | `/guides/streaming` | docs |
| B-056 | R | Reconnecting with `last_sequence=N` replays **only newer** events, never the full history | `/guides/streaming` | docs |
| B-057 | R | Omitting `last_sequence` (or passing `0`) replays the full event history for the job | `/guides/streaming` | docs |
| B-058 | R | `document_sync` fires only when `document_html` was provided, and arrives before any `intermediate` or `proposed_change_batch` | `/guides/streaming` | docs |
| B-059 | R | `continue_prompt.content`, `documents_changed.content` and `model_fallback.content` are all JSON-encoded strings needing a second parse | `/guides/streaming` | docs |
| B-060 | R | `usage` is emitted after `final` | `/guides/streaming` | docs |
| B-061 | R | `documents_changed` fires on auto-apply turns touching 2+ documents, and on any turn creating a document — in either approval mode | `/guides/streaming` | docs |
| B-062 | R | `model_fallback` fires only when the requested tier was unresponsive and the request was served on `pro`; billing is unchanged | `/guides/streaming` | docs |

## Errors

| ID | T | Behaviour | Source | Status |
|---|---|---|---|---|
| B-063 | R | Every error response is JSON carrying a `detail` field | `/errors/error-codes` | docs |
| B-064 | R | An application `429` is JSON and **always** carries `Retry-After` in seconds | `/errors/rate-limits` | docs |
| B-065 | R | On quota exhaustion the `429` also carries `X-Usage-Limit`, `X-Usage-Used`, `X-Usage-Remaining`; those headers appear **only** on the `429` | `/errors/rate-limits` | docs |
| B-066 | R | An infrastructure `429` is **plain text** with no `Retry-After`; clients must treat any non-JSON `429` as transient and back off with jitter | `/errors/rate-limits` | docs |
| B-067 | R | Clients must branch on status and headers, never on the `detail` wording | `/errors/rate-limits` | docs |
| B-068 | R | `415` returns the supported-type list verbatim in `detail` | `/errors/error-codes` | docs |
| B-069 | R | A legacy `.doc` upload returns **`400`** with a converter-unavailable message, not the documented `415` | live, refuting `/errors/error-codes` | **DRIFT** (F-005) |
| B-070 | R | `413 request_too_large` is structured: `error_code`, `message_user`, `request_size_mb`, `max_size_mb`, `suggested_action: "split_request"`, `contact_email`, `support_event_id` | `/errors/error-codes` | docs |
| B-071 | R | `413 document_too_large` nests the same structure under `detail` with `suggested_action: "email_request"` and a `format` field | `/errors/error-codes` | docs |
| B-072 | R | A body above the ~32 MB gateway ceiling is rejected as **HTML**, not JSON — do not try to parse it | `/errors/error-codes` | docs |
| B-073 | R | The scale refusals `DOCUMENT_TOO_COMPLEX` (25,000 sections/doc) and `SESSION_TOO_FULL` (30,000 sections/session) are `413`s carrying `limit_expandable: true`, the observed and maximum counts, and `contact_email` | `/errors/rate-limits` | docs |
| B-074 | B | Those limits are expandable, not caps — the documented recovery is `POST /v1/limits/increase-request` (`request_limit_increase`), not failure | `openapi@ac0d44c` `/v1/limits/increase-request` | spec |
| B-075 | R | Synchronous `/v1/chat` past the 30-minute cap returns `504` with a `detail` string; async instead **completes** and persists a friendly wrap-up as the job's response | `/errors/error-codes` | docs |
| B-076 | R | An out-of-enum `format` on export returns `422` in FastAPI list form (`type`, `loc`, `msg`) | `/errors/error-codes` | docs |

## Upload, parse and export

| ID | T | Behaviour | Source | Status |
|---|---|---|---|---|
| B-077 | R | `POST /v1/documents/upload` is `multipart/form-data` (`file`, `session_id`) and returns `ProcessDocumentResponse` | `openapi@ac0d44c` | spec |
| B-078 | B | `ProcessDocumentResponse` requires `session_id`, `filename`, `status`, `parse_mode`; `html`, `chunks_count`, `version_id`, `job_id`, `page_setup`, `warnings` are nullable | `openapi@ac0d44c` ProcessDocumentResponse | spec |
| B-079 | R | An upload **replaces** the focused document by default; `open_mode=new_focused` or `background` opens it as an additional document | `/concepts/documents` | docs |
| B-080 | B | `page_setup` is populated for DOCX and PDF sources and `null` when the format carries no geometry; `null` implies US-Letter with 1 in margins | `/concepts/documents`, `openapi@ac0d44c` DocumentState | spec |
| B-081 | R | Export accepts exactly one of `html`, `session_id`, `upload_id` | `/concepts/documents` | docs |
| B-082 | R | Export `format` ∈ `docx` (default), `pdf`, `html`, `markdown`, `txt`; `doc` is a deprecated legacy alias | `openapi@ac0d44c` ExportRequest | spec |
| B-083 | R | The export `200` is a **binary download** (`PK\x03\x04`, DOCX media type, RFC 5987 `Content-Disposition`); `openapi.json` wrongly declares it `application/json` | live, confirming `/concepts/documents` | **DRIFT** (F-002) |
| B-084 | R | Non-fatal export issues ride the `X-Export-Warnings` header as a **base64-encoded JSON list**, exposed via `Access-Control-Expose-Headers` | `/concepts/documents` | docs |
| B-085 | R | Export size tiers: ≤20 MB inline; 20–100 MB via pre-signed upload then `upload_id`; >100 MB via the email-request endpoint | `/concepts/documents` | docs |
| B-086 | R | A pre-signed upload URL is valid 5 minutes; the blob is retained 24 hours; a download URL is valid 15 minutes | `/concepts/documents`, `/mcp/available-tools` | docs |
| B-087 | B | `options.filename` wins over the legacy top-level `filename`; a matching extension is never doubled, a missing one is appended | `openapi@ac0d44c` ExportRequest, `/concepts/documents` | spec |

## Billing and quota

| ID | T | Behaviour | Source | Status |
|---|---|---|---|---|
| B-088 | B | One operation covers up to 25 sections of targeted edits in a single request | `/introduction/quickstart` | docs |
| B-089 | B | Uploads, parsing, exports and downloads are free; searches are billable | `/introduction/quickstart`, `/mcp/available-tools` | docs |
| B-090 | B | A request that errors out or is cancelled is not billed for the edit it never made | round task document | docs |
| B-091 | M | `get_account_status` and `request_limit_increase` are explicitly non-billable | `/mcp/available-tools` | docs |
| B-092 | B | Free tier is 500 operations/month; Plus 2,000; Pro 10,000 | `/errors/rate-limits` | docs |
| B-093 | R | `whoami` reports the tier bucket only and omits active promotional operations, under-reporting spendable quota (500 shown against 10,500 held) | live | **DRIFT** (F-001) |

## MCP surface

| ID | T | Behaviour | Source | Status |
|---|---|---|---|---|
| B-094 | M | The endpoint is `https://api.superdocs.app/mcp/`, Streamable HTTP; both `/mcp` and `/mcp/` are accepted | `/mcp/setup` | docs |
| B-095 | M | The surface is 38 tools and 4 workflow prompts | `/mcp/available-tools`, `/mcp/plugin` | docs |
| B-096 | M | The handshake returns an `instructions` field | `/mcp/setup` | docs |
| B-097 | M | Tools and prompts are served live from the backend — the plugin is only a manifest, so the surface can change with no client release | `/mcp/plugin` | docs |
| B-098 | M | The four-call contract maps to `upload_document_base64` / `process_uploaded_document` → `chat` / `chat_async` → `approve_change` → `export_document` | `/mcp/available-tools` | docs |
| B-099 | M | `process_uploaded_document` returns a compact result by default: `html` is `null` unless `return_html=true` | `/mcp/available-tools` | docs |
| B-100 | M | `list_documents`, `list_session_documents` and `get_document_detail` omit HTML bodies unless `include_html=true` | `/mcp/available-tools` | docs |
| B-101 | M | `archive_document` on a document open in another session fails `409 document_in_use` and archives nothing unless `force=true` | `/mcp/available-tools` | docs |
| B-102 | M | `get_document_detail`'s free `structure` outline is the documented way to verify an edit landed — never export just to check | `/mcp/available-tools` | docs |

## Discovered live

Behaviours no document describes, found by recording. The mock serves these because the
service does them; each one a client would otherwise meet for the first time in production.

| ID | T | Behaviour | Source | Status |
|---|---|---|---|---|
| B-103 | R | `POST /v1/documents/upload` and `/upload-base64` publish an empty `200` schema, so their response shape is undocumented; `POST /v1/uploads/{upload_id}/process` does declare `ProcessDocumentResponse` and **conforms to it exactly** | live vs `openapi@ac0d44c` | **DRIFT** (F-004) |
| B-104 | R | SSE `sequence` is not strictly increasing: an `intermediate` and the `final` were both emitted as `11`, with `10` skipped, which can make a client resuming from `last_sequence` miss `final` entirely | live vs `/guides/streaming` | **DRIFT** (F-006) |
| B-105 | B | On a HITL review pause `metadata.awaiting_kind` is **absent**, not set to a review-specific value — integration code must treat absence as the review branch | live | live |
| B-106 | B | The `usage` block on a completed job carries a `promotions[]` array with per-promotion `ops_granted` / `ops_remaining` / `expires_at`, which `UsageInfo` does not describe | live | live |
| B-107 | R | `.odt` uploads succeed and parse into chunks, though ODT appears in neither the `415` supported-type message nor the live `supported_formats` list; `page_setup.source` is reported as `"docx"` | live | **DRIFT** (F-003) |
| B-108 | R | The `413 DOCUMENT_TOO_COMPLEX` body carries an undocumented `request_increase` block (`endpoint`, `mcp_tool`, `agent_hint`) and a live `supported_formats` list | live | live |
| B-109 | B | Billing draws from the promo bucket ahead of the tier bucket: a billable turn charged `bucket_used: "promo"` while the tier bucket stayed at 0 used | live | live |
| B-111 | R | Exporting from a session that holds no document returns `404` with `"No document loaded in this session. Load a document first, then export."` — an actionable message rather than an empty file | live | live |
| B-110 | R | A whole-document edit across 400 sections completes in one turn, charging 16 operations (one per 25 sections) and summarising as "400 sections edited, rest untouched" | live | live |


---

## Coverage

`contract/` must carry at least one test naming each ID above. `scripts/check_ledger_coverage.py`
(Phase 3) parses the `B-` references out of the test suite, diffs them against this file and
fails CI on any gap, in either direction — an ID with no test, or a test citing an ID that does
not exist.

Counts below are generated by `scripts/ledger_stats.py`, not typed. It also checks for
duplicate and skipped IDs.

**102 behaviours · 41 REST-only · 12 MCP-only · 49 both · 3 flagged VERIFY**
**Sources: 26 from the pinned spec · 72 from prose docs · 1 confirmed live**
