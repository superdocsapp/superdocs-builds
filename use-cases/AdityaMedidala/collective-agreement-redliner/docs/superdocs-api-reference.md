# SuperDocs API reference — the calls this build actually uses

Fetched from docs.superdocs.app/llms-full.txt on 2026-08-12. This is a curated
subset for THIS build, not the full platform surface — see the live docs for
anything not covered here.

Base URL: `https://api.superdocs.app`
Auth: `Authorization: Bearer sk_...` on every call.

## The four calls this build is built around

### 1. Load documents into a session

**CBA draft (the editable working document):**
`POST /v1/documents/upload-base64` — parses into chunk-ID'd HTML, one chunk per
paragraph/heading/table row/cell. This is what enables targeted redlines
("remove row 3 of the pricing table" works the same way for a CBA clause).
Pass `session_id` to load directly into a session.

**Union / employer position papers (read-only reference, NOT editable):**
`POST /v1/attachments/upload-base64` — async, poll `GET /v1/jobs/{job_id}`
until `status=completed`, or `GET /v1/attachments/status/{session_id}` to
check both at once. The AI can search/reference these but never edits them —
exactly the semantic we want: positions inform redlines, they aren't targets.

### 2. Propose a redline round (human-in-the-loop)

`POST /v1/chat/async` with `approval_mode="ask_every_time"` — returns
`job_id` immediately, does NOT apply anything yet.

```json
{
  "message": "Compare the current agreement against the attached union and
    employer position papers. Propose redlines that reconcile differences
    where possible, and flag anywhere the two sides still disagree.",
  "session_id": "<negotiation_id>",
  "approval_mode": "ask_every_time"
}
```

Poll `GET /v1/jobs/{job_id}` until `status == "awaiting_approval"` (also
watch for `in_progress` as a non-terminal status while polling — it's real,
just not called out in the surface docs). The response's
`metadata.pending_changes` is a list of entries shaped like:

```json
{
  "change_id": "b68af6e6-...",
  "chunk_id": "361010b7-...",
  "operation": "edit",
  "document_id": "doc_primary",
  "old_html": "<p data-chunk-id=\"...\">...</p>",
  "new_html": "<p data-chunk-id=\"...\">... <mark>...</mark></p>",
  "ai_explanation": "..."
}
```

`change_id` is the id for THIS specific proposal (needed to approve/deny
it — see below); `chunk_id` is the stable clause identifier that persists
across rounds (what our open-items tracker keys on).

### 3. Approve or reject each proposed redline

`POST /v1/chat/{session_id}/approve` — **one decision per call**, not a
batch. Body: `{"job_id": "<job_id>", "change_id": "<change_id>", "approved":
true|false, "feedback"?: "string"}`. `job_id` and `approved` are required;
the decision is matched to a specific proposal by `change_id` (from
`pending_changes`, above) — `chunk_id` is accepted in the payload but
ignored, so always send `change_id`. Response: `{"status": "ok", "message":
"...", "batch_complete": true|false}` — `batch_complete` is `true` once
every pending change on that job has been decided.

Approved changes apply atomically; denied ones are discarded (never billed).
`feedback` on a denial lets the AI revise on the next round instead of just
dropping the idea — useful for "close but the notice period is wrong."

Poll `GET /v1/jobs/{job_id}` again until `status == "completed"` (only once
`batch_complete` is true across all pending changes on that job).

### 4. Export the redlined agreement

`POST /v1/documents/export` with `session_id` + `format` (default `docx`).
Returns the file directly (or use `POST /v1/downloads` for a pre-signed URL
if running headless with shell access).

## The call that makes the open-items tracker possible

`GET /v1/sessions/{session_id}/jobs` — full job history for one session,
most recent first. **This is SuperDocs' own durable audit trail.** Our
tracker reconciles against this rather than re-deriving it from scratch —
see `services/tracker_service.py`.

Response is `{"jobs": [...], "total": N}` — **not** a bare list. Each
entry in `jobs` is shaped exactly like a `GET /v1/jobs/{job_id}` response
(same `job_id`, `status`, `metadata.pending_changes`, etc). There is
**no separate entry per approve/deny decision** — a job still awaiting
decisions carries its proposals at `metadata.pending_changes` (see
above); once fully decided, the SAME job entry (now `status: "completed"`)
carries the outcome at `result.document_changes.changes`, a list of
`{"status": "approved"|"rejected"|..., "chunk_id": "...", "new_html":
"..."}`. So one job_id maps to one history entry whose shape changes as
it moves through pending → decided, not one entry per event.

`GET /v1/sessions/{session_id}/history` — full conversation + document
state, useful for resuming a negotiation session on a different day
(sessions never expire).

## Multi-document sessions (for holding CBA + both positions together)

`POST /v1/sessions/init` — create a session and open N saved documents into
it in one call. We use this to start a negotiation: CBA draft becomes the
focused editable document, positions load separately as attachments (not
documents — see above).

## Errors worth knowing about up front

- `413 DOCUMENT_TOO_COMPLEX` / `SESSION_TOO_FULL` — stability limits, not
  hard caps, expandable via `/v1/limits/increase-request`. Unlikely at CBA
  scale but the brief warns operations can be slow/fail on first try — retry.
- `504` on `/v1/chat` after 30 min — use `/v1/chat/async` for anything that
  might run long, which we already do for every redline round.
- Every `/v1/chat*` response carries a `usage` object
  (`monthly_used`/`monthly_limit`/`monthly_remaining`) — log it, don't
  silently burn the 10,000-op grant.

## The documented gotcha from the brief — not observed on this codepath

The brief warns "proposed-change content arrives as a JSON-encoded string
and needs a second parse." `superdocs_client.py`'s
`parse_pending_changes` still double-parses defensively (checking
`content`/`diff`/`html` keys), but on the actual `edit`-operation
`pending_changes` entries this build exercises, the redline arrives as
plain `old_html`/`new_html` strings (see section 2, above) — no JSON-
encoded `content` field, nothing to double-parse. The gotcha may still be
real for other operation types or endpoints not exercised here; treat the
defensive double-parse as cheap insurance, not as evidence the gotcha
applies to every pending_changes entry.
