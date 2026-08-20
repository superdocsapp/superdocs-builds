# SuperDocs API — Capabilities Catalog

Research reference for the SuperDocs Full-Stack AI Engineer assignment (Task 2B,
classroom-app). Compiled 2026-08-11 from the official documentation
(`llms-full.txt`, the OpenAPI-derived API reference pages) — the same
authoritative sources the live integration was verified against.

**Status line:** the integration classroom-app ships matches the authoritative
docs exactly on every contract it touches; the discrepancies found are in the
web-facing prose pages, not in the OpenAPI-derived reference (see §11).

---

## 1. API surface at a glance

Base URL `https://api.superdocs.app`. Auth: `Authorization: Bearer sk_...`.
Every response includes a `usage` block (`monthly_used`, `monthly_limit`,
`monthly_remaining`, `was_billable`, `subscription_tier`) — on 429 responses it
arrives as `X-Usage-*` headers instead.

| Group | Endpoints |
|---|---|
| **Chat** | `POST /v1/chat` (sync) · `POST /v1/chat/async` (job) · `POST /v1/chat/{session_id}/approve` (HITL) · `POST /v1/chat/{session_id}/continue` (large-edit pause) · `GET /v1/chat/{session_id}/stream` (SSE) |
| **Jobs** | `GET /v1/jobs` · `GET /v1/jobs/{job_id}` · `POST /v1/jobs/{job_id}/cancel` · `GET /v1/sessions/{session_id}/jobs` |
| **Sessions** | `GET /v1/sessions` · `GET /v1/sessions/{id}/history` · `POST /v1/sessions/{id}/revert` · `POST /v1/sessions/{id}/redo` · `POST /v1/sessions/init` · `GET /v1/poll/{session_id}` (long-poll, B2B orgs) |
| **Documents** | `POST /v1/documents/upload` · `POST /v1/documents/upload-base64` · `GET /v1/documents` · `GET /v1/documents/{id}` · `PATCH /v1/documents/{id}` (rename + parts) · `DELETE /v1/documents/{id}` (archive) · `POST /v1/documents/{id}/unarchive` · `POST /v1/documents/export` · `POST /v1/documents/export/email-request` · `POST /v1/documents/images/upload(-base64)` |
| **Multi-doc** | `GET /v1/sessions/{id}/documents` · `POST .../documents/open` · `POST .../documents/blank` · `POST .../documents/{doc}/focus` · `DELETE .../documents/{doc}` · `POST .../documents/{doc}/save` (human autosave) · `POST .../chunks/{chunk_id}/re-edit` (conflict resolution) · `GET /v1/sessions/{id}/doc-events` (cross-session updates) |
| **Attachments** | `POST /v1/attachments/upload` · `POST /v1/attachments/upload-base64` · `GET /v1/attachments/status/{session_id}` · `DELETE /v1/attachments/{id}` |
| **Templates** | `POST /v1/templates/upload(-base64)` · `GET /v1/templates` · `DELETE /v1/templates/{id}` |
| **Uploads (large)** | `POST /v1/uploads` (pre-signed PUT URL) · `POST /v1/uploads/{upload_id}/process` · `POST /v1/downloads` (pre-signed download URL) |
| **Memory** | `DELETE /v1/users/me/cross-session-memory` (web-app token only) |
| **Account / agent** | `GET /v1/agents/whoami` · `POST /v1/agents/handoff` · `POST /v1/agents/request-upgrade` · `POST /v1/promo/redeem` · `GET /v1/users/me/api-keys` · `POST /v1/users/me/api-keys` · `DELETE /v1/users/me/api-keys/{key_id}` |
| **Meta** | `GET /health` · `GET /health/deep` · `GET /.well-known/api-catalog` · `GET /` |

Web-app-only (reject `sk_` keys with 401): everything under `/v1/users/*` except
api-keys management, plus session deletion. From an API-key context, read usage
from chat responses / SSE `usage` events; key verification is `GET /v1/sessions`.

---

## 2. The HITL approval contract (what classroom-app depends on)

The single approval path. **Only** endpoint in the authoritative reference:
`POST /v1/chat/{session_id}/approve`. There is no job-level approve endpoint.

Request bodies (all three shapes require **top-level `approved`** — omitting it
yields 422 even when every entry in `changes[]` carries its own):

```jsonc
// Single change
{ "job_id": "…", "change_id": "ch_1", "approved": true }

// Batch — same decision for all
{ "job_id": "…", "approved": true, "changes": [{"change_id": "ch_1"}, {"change_id": "ch_2"}] }

// Batch — per-change decisions (the shape classroom-app sends)
{ "job_id": "…", "approved": true, "changes": [{"change_id": "ch_1", "approved": true}, {"change_id": "ch_2", "approved": false}] }

// Deny with feedback (single or per-change): add "feedback": "…" — the AI
// receives it and may propose a REVISED change, so polling must handle
// multiple rounds of awaiting_approval, not just one.
```

The nested identifier is **`change_id`**, never `chunk_id`. `change_id` is a
per-turn identifier; `chunk_id` is the document section the change targets. The
docs prose sometimes says "chunk_id" loosely; every concrete example and the
OpenAPI-derived schema use `change_id`.

`pending_changes[]` from `GET /v1/jobs/{job_id}` at `awaiting_approval`:

```jsonc
{ "change_id": "ch_1", "operation": "edit" | "create" | "delete",
  "chunk_id": "…", "old_html": "<p>…</p>", "new_html": "<p>…</p>",
  "ai_explanation": "…", "insert_after_chunk_id": null }
```

`awaiting_approval` has two flavours — branch on `metadata.awaiting_kind`:
- absent / not `continue_prompt` → HITL change review, respond via `/approve`;
- `"continue_prompt"` → a large edit paused partway (`metadata.continue_prompt`
  = `{message, done, total, remaining}`); there are **no** `pending_changes`;
  resume with `POST /v1/chat/{session_id}/continue` `{job_id, continue: true|false}`.
  Calling `/approve` on a continue-prompt pause is rejected with 409 and
  vice-versa.

After approval the job resumes; poll until `status == "completed"`, then read
`result.document_changes.updated_html`. The job is cleaned up after ~1 hour if
an `awaiting_approval` pause is never answered. Revert returns 409 while any
job is in flight (`pending`/`in_progress`/`awaiting_approval`) on the session.

### Approval modes

| Mode | Behaviour |
|---|---|
| `approve_all` | Auto-apply; one call returns final HTML. Server/batch/agent flows. |
| `ask_every_time` | Job pauses at `awaiting_approval`; HITL via `/approve`. |

Recommended UX pattern in the docs: default `approve_all`, expose review mode
as an opt-in toggle persisted in localStorage. Going straight to
`ask_every_time` is valid for high-stakes products — which is what a grading
workflow is.

---

## 3. Model selection

Per-request params on `/v1/chat` **and** `/v1/chat/async` (also `approve`-adjacent
flows inherit the job's tier). Account default set in the web app; per-request
wins.

| `model_tier` | Best for | Speed |
|---|---|---|
| `core` (default) | everyday editing | fast |
| `turbo` | speed-critical / batch | fastest |
| `pro` | complex analysis, multi-step edits | moderate |
| `max` | challenging / nuanced documents | slower |

| `thinking_depth` | Behaviour |
|---|---|
| `fast` | minimal reasoning; tight budget; can over-narrow scope on ambiguous prompts |
| `balanced` (default) | dynamic — model decides per request |
| `deep` | up to ~16k reasoning tokens, +3–8s latency, ~6× output tokens |

Guidance relevant to a grading product: for legal/regulatory/compliance
documents the docs say to default to `pro`/`max`; `deep` pays off when "one bad
output is more expensive than the extra tokens" (few-but-important edits), and
is wasted on high-volume or latency-dominated flows. `turbo` + fast is the
batch-processing recommendation. `model_fallback` events (SSE) or
`metadata.intermediate_responses` (polling) note when a requested tier was
auto-replaced by `pro` upstream.

---

## 4. SSE streaming

`GET /v1/chat/{session_id}/stream?job_id=…&api_key=…&last_sequence=…`

- `EventSource` cannot set headers → API key as **query parameter**.
- Nine event types: `intermediate`, `proposed_change_batch`, `document_sync`,
  `continue_prompt`, `documents_changed`, `model_fallback`, `final`, `usage`,
  `error`.
- `proposed_change_batch` is the **only** event carrying proposed changes; the
  whole turn arrives as one event whose `changes[]` holds everything (single
  change = array of length 1). **Double-parse trap:** the event `data` is JSON
  and `data.content` is a *JSON-stringified string* that must be parsed a
  second time (unlike `final.result`, which is already an object). Missing the
  second parse is the #1 cause of empty diff cards.
- Batch payload: `{type: "batch_approval"|"single_approval", batch_id,
  batch_total, changes: [{change_id, operation, chunk_id, old_html, new_html,
  ai_explanation, document_id, insert_after_chunk_id}]}`.
- `document_sync` (start of stream, only when `document_html` provided): apply
  the prepared HTML so editor chunk IDs match what the AI will reference.
- Reconnect: every event carries a monotonic `sequence`; reconnect with
  `last_sequence=<n>` replays only newer events; omit (or 0) for full history.
- Also delivered to pollers: `GET /v1/jobs/{job_id}` returns the same typed
  events in `metadata.intermediate_responses`.
- `continue_prompt` event mirrors §2's `awaiting_kind` pause; respond via
  `/continue`.

---

## 5. Async job lifecycle

`POST /v1/chat/async` → `{job_id, session_id, status}`. Poll `GET /v1/jobs/{job_id}`.

| Status | Meaning | Action |
|---|---|---|
| `pending` | queued | poll |
| `in_progress` | processing | poll |
| `awaiting_approval` | paused — check `metadata.awaiting_kind` | `/approve` or `/continue` |
| `completed` | done | read `result` |
| `failed` | error | read `error` |
| `cancelled` | cancelled | none |

- Job state is durable across server restarts; jobs survive ~1h unanswered.
- `POST /v1/jobs/{job_id}/cancel` cancels only `pending`/`in_progress` jobs;
  already-applied changes are preserved.
- Jobs list: `GET /v1/jobs` (filter by status, `compact=true` for
  status/progress only); per-session: `GET /v1/sessions/{session_id}/jobs`.
- Latency guidance: single-section edits seconds; large multi-section edits
  can pass 30s — hence async for anything long.

---

## 6. Files — durable documents

Every uploaded/edited document persists as a File with a stable
`document_id` (UUID), independent of any session. This is the layer above
sessions: sessions are threads, Files are documents. Open is **share-attach,
not copy** — edits flow back to the one underlying File.

- `GET /v1/documents` — list (token-light; `include_preview=true` for a
  thumbnail; `limit`/`offset` paging).
- `GET /v1/documents/{id}` — detail + **free `structure` outline** (headings,
  section/block counts, media counts) — the docs' recommended "did my edit
  land?" verification that costs nothing; `include_html=true` for the body.
- `POST /v1/sessions/{id}/documents/open` — open Files into a session
  (first listed is focused); `POST /v1/sessions/init` — create session + open
  Files in one call.
- `PATCH /v1/documents/{id}` — rename / update headers, footers, footnotes,
  endnotes, comments, sections.
- `DELETE /v1/documents/{id}` — **soft delete** (archived; recoverable ~30
  days then purged). 409 `document_in_use` if open elsewhere unless
  `?force=true`. `POST /v1/documents/{id}/unarchive` restores.
- Billing: documents are persisted automatically; only AI edits are billed.

---

## 7. Sessions

- You choose the `session_id` (any string) — the resume handle. Sessions
  persist across restarts and **never expire**; nothing is billed unless used.
- Follow-up turns don't need `document_html` re-sent — the server keeps the
  document; re-send only to replace it or to sync external edits.
- `GET /v1/sessions/{id}/history` — full conversation + document state
  (`turn_index`, `checkpoint_id`, `document_state`, `editor_action`).
- `POST /v1/sessions/{id}/revert {turn_index}` — rewinds chat **and** document
  to before a user message; returns `compose_text` (to re-send an edited
  version), `reverted_to_turn`, `document_state`. 409 while a job is in
  flight; 422 if target predates the revert feature. `POST /v1/sessions/{id}/redo`
  undoes a revert (immediately after; once a new message is sent the timeline
  diverges).
- Isolation is per API key owner; B2B2C pattern is to prefix session ids per
  end-user (`user_123_draft-contract`).
- `GET /v1/sessions/{id}/doc-events` — lightweight poll (not SSE) for
  `document_updated` events from OTHER sessions holding the same document.

---

## 8. Multi-document sessions

One session can hold several open documents ("tabs"), one focused. Chat turns
target the focused document unless `document_id` (session-local slot id or
durable UUID — either accepted) is passed, or the message names a document.

- Roster: `GET /v1/sessions/{id}/documents` (token-light; `include_html=true`
  for bodies; `durable_document_id` mapping documented).
- `focus` / `close` (with `next_focus`), `blank` (new tab), `save` (persist a
  **human** edit without an AI turn — non-billable).
- Changes in `proposed_change_batch.changes[]` carry `document_id` so review
  UIs can group per document; `documents_changed` fires on multi-document
  auto-apply and on created documents (creation applies immediately in either
  approval mode).

---

## 9. Attachments — reference material

Read-only context for the AI to consult while editing (distinct from the
editable document): "rewrite section 3 to match the style guide PDF I
attached". Async processing; queryable via semantic search + multimodal
vision.

- `POST /v1/attachments/upload` (multipart) or `/upload-base64`; returns a
  `job_id` (same job id space / poll path as chat jobs).
- `GET /v1/attachments/status/{session_id}` — per-attachment state
  (pending/processing/completed/failed) + extracted text length + chunk count.
- `DELETE /v1/attachments/{id}` — remove / cancel processing.
- Formats: pdf, docx, doc, odt, html/htm, txt, rtf, md, tex (+zip projects),
  images (png/jpg/jpeg/gif/webp).
- Max 100 MB via pre-signed flow; ~20 MB direct; over ~100 KB the pre-signed
  path is preferred anyway.

---

## 10. Templates

Named, session-scoped→actually user/org-scoped reusable document templates
(NDA, contract, SOP, letterhead). Uploaded via `/v1/templates/upload(-base64)`
(synchronous), listed via `GET /v1/templates`, soft-deleted. The AI consults
them when **drafting new documents** ("draft an NDA using my standard
template"). Not instruction bundles — for influencing review behaviour, use
attachments or the prompt itself.

---

## 11. Cross-session memory & search (opt-in)

Two flags on `chat`/`chat_async` (off by default, owner-scoped):

| Field | What it does |
|---|---|
| `cross_session_memory: true` | AI applies durable preferences learned from your past chats (tone, spelling conventions, standing facts) and may note new ones. |
| `cross_session_search: true` | AI can find and reuse your own prior documents/chats ("pull the payment terms from last month's contract"). |
| `cross_session_memory_key` | per-end-customer memory partition under one API key (B2B2C). |
| `cross_session_scope` | list of session ids narrowing the search boundary. |

`DELETE /v1/users/me/cross-session-memory?memory_key=…` wipes a note
(web-app token only; MCP tool `clear_cross_session_memory` is the API-key
path). Note: the earlier "Chat Context (add-document / modify-prompt /
set-criteria / cleanup)" feature text appears on the features page but **does
not exist in the current OpenAPI-derived reference** — cross-session context
and attachments are the shipped equivalents (see §13).

---

## 12. Export

`POST /v1/documents/export`. Three ways to supply the document: `html`
(inline), `session_id` (session state), `upload_id` (large docs via
pre-signed upload).

- Formats: `docx` (default, native Open XML), `pdf`, `html` (standalone CSS),
  `markdown`, `txt`. `doc` is a legacy alias (Word-compatible HTML) — new
  integrations should not use it.
- `options`: `paper_size` (Letter/A4/A3/Legal), `orientation`, `margins`
  (narrow/normal/wide/custom + `custom_margins_inches`), `filename`
  (precedence over top-level; extension never doubled), `embed_images`
  (HTML only, raises cap 100→150 MB), `watermark_text`/`watermark_opacity`
  (PDF only).
- **Warnings:** non-fatal issues in `X-Export-Warnings` header — a
  **base64-encoded JSON list** (`[{code, message, detail}]`), exposed via
  `Access-Control-Expose-Headers` so browser `fetch` can read it. Known codes:
  `image_download_failed`, `mermaid_render_failed`, `mermaid_timeout`,
  `excalidraw_corrupt`, `footnote_orphan`, `track_change_unmatched`,
  `field_code_unsupported`, `watermark_skipped`, `embed_image_skipped`,
  `size_cap_warning`, `header_footer_degraded`, `sections_degraded`,
  `svg_png_conversion_failed`, `math_partial_fidelity`.
- Large docs: `POST /v1/uploads` → 5-min pre-signed PUT (up to 100 MB) →
  `POST /v1/uploads/{upload_id}/process` → export with `upload_id`. Very
  large: `POST /v1/documents/export/email-request` (async, emailed link,
  24h SLA). `POST /v1/downloads` returns a 15-minute signed GET URL for
  agent flows.

---

## 13. Docs discrepancies found (web prose vs authoritative reference)

| Claim (web page) | Authoritative reference says | Impact |
|---|---|---|
| async-jobs page table lists `POST /v1/jobs/{job_id}/approve` | The **only** approve endpoint is `POST /v1/chat/{session_id}/approve` (OpenAPI-derived catalog + every curl/JS/Python example + the integration-starter contract summary) | None — classroom-app uses the correct one. Do not "fix" it to the job-level path. |
| async-jobs page table lists `POST /v1/jobs/{job_id}/retry` | No retry endpoint exists in the reference; failure family (`failed`) has no retry — start a new job | None (classroom-app never retries). |
| features page describes "Chat Context" (add-document / modify-prompt / set-criteria / cleanup / sources / sync / info) | Not present in the current reference; the shipped equivalents are attachments (§9) and cross-session memory/search (§11) | If a rubric-as-context feature is planned, build it on attachments, not the unshipped context endpoints. |
| features page: job statuses include `inflight`, `queued`, `scheduled`, `partial`, `unknown` | Job statuses are `pending`, `in_progress`, `awaiting_approval`, `completed`, `failed`, `cancelled` | Polling loops should not branch on statuses that never occur. |

---

## 14. classroom-app: what matches / what is unverified

| classroom-app behaviour | Docs status |
|---|---|
| `POST /v1/documents/upload-base64` with `file_base64` | ✔ current contract |
| `POST /v1/chat/async` with `approval_mode: "ask_every_time"` | ✔ current contract |
| `GET /v1/jobs/{job_id}` polling for `awaiting_approval` → `metadata.pending_changes` | ✔ current contract |
| `POST /v1/chat/{session_id}/approve` `{job_id, approved, changes: [{change_id, approved}]}` | ✔ current contract (top-level `approved` required — classroom-app sends it) |
| `change_id` ≠ `chunk_id` | ✔ docs examples use `change_id`; `chunk_id` is the target section |
| Export `POST /v1/documents/export` `{format: "docx"}` + `X-Export-Warnings` | ✔ current contract (header is base64 JSON) |
| Treating `awaiting_kind` as always HITL | ⚠ documented gap: a `continue_prompt` pause would currently be misinterpreted as a change review (no `pending_changes` would appear; the app should surface the continue prompt or cancel). Not observed live, but the docs define the branch. |
| Rejecting without feedback / single-round approval | ✔ valid; docs only *recommend* feedback for revision loops |
| No `model_tier`/`thinking_depth` sent | ✔ valid — defaults `core` + `balanced` are the documented general-purpose defaults |

---

## 15. Opportunities for classroom-app (ranked)

1. **Attach the teacher's rubric as a reference attachment** (`.pdf`/`.docx` +
   `POST /v1/attachments/upload-base64` + poll `/v1/attachments/status/{session_id}`),
   then instruct the review to grade against it. Shipped, documented, and the
   single biggest feature lever (current docs' equivalent of "chat context").
2. **`model_tier` for the review job** — grading is a "few-but-important"
   workload: `pro` + `balanced` (or `deep` on demand) is the documented
   recommendation for high-stakes text; `turbo` only for batch. One request
   field; the review instruction already exists.
3. **SSE instead of polling** — `GET /v1/chat/{session_id}/stream` replaces
   the step poll in the workflow UI. Constraint: the key must stay server-side,
   so the backend would proxy the stream (the frontend cannot hold `sk_`).
   `last_sequence` makes reconnect safe; `proposed_change_batch` arrives as
   one event with the whole review batch (double-parse required).
4. **Files for retention** — persist each reviewed document as a durable
   File; `GET /v1/documents/{id}` `structure` is the free "did it land?"
   check before attaching to Classroom. Rename to a tidy title
   (`student-essay_reviewed.docx`).
5. **`continue_prompt` handling** — branch on `metadata.awaiting_kind` before
   treating `awaiting_approval` as a change review (§14 ⚠).
6. **Cross-session memory per teacher** — `cross_session_memory_key` = teacher
   id could carry stable grading preferences ("comment positively first") into
   future sessions without storing anything in classroom-app.
7. **Usage surfacing** — the `usage` block in every response / SSE `usage`
   event / 429 `X-Usage-*` headers lets the teacher see remaining operations
   and the app fail honestly with "quota exhausted" instead of an opaque error.

---

## 16. Source URLs

- Full AI reference (556 KB): https://docs.superdocs.app/llms-full.txt
- Index: https://docs.superdocs.app/llms.txt
- API reference (OpenAPI-derived): https://docs.superdocs.app/api-reference/endpoints.md
- OpenAPI spec (auth-protected): https://api.superdocs.app/openapi.json
- Guides: human-in-the-loop, async-jobs, streaming (SSE), model-selection,
  multi-document, server-integration, agent-tool-integration, chat-context,
  integration-starter-prompt, concurrent-editing, export — all under
  https://docs.superdocs.app/guides/
- Concepts: sessions, documents, files, attachments, templates,
  cross-session-context — all under https://docs.superdocs.app/concepts/
- MCP: https://docs.superdocs.app/mcp/available-tools (38 tools)
