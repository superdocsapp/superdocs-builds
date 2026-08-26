# SuperDocs OpenAPI — spec ambiguities found (Task 2.1)

## 1. `proposed-change` content is a JSON-encoded string (needs a second parse)
Proposed-change content in the async-chat/approve flow arrives as a JSON-ENCODED STRING,
not an object; it needs a second parse. The spec types it as an object, so a naive typed
client yields empty diff cards where every field reads `undefined`.
- Impact: the single most common empty-diff integration bug.
- Fix: type it as string + document the second parse, or return a decoded object.

## 2. SSE auth token in the URL query string
`GET /v1/chat/{session_id}/stream` takes `token`/`api_key` as a QUERY PARAMETER (EventSource
can't set headers). A full account token in the URL leaks via access logs, proxies, history,
and Referer.
- Fix: short-lived single-use stream token (not the account key), or cookie auth.

## 3. `approve` prose says `chunk_id`, but the schema needs `job_id` + `change_id`
The endpoint description says "for each proposed change (with chunk_id and HTML diff), respond
approved=...". But `ApprovalRequest` **requires `job_id`** and identifies changes by **`change_id`**,
not `chunk_id` (which is literally `"new"` for a create op). Sending `chunk_id` or omitting
`job_id` returns HTTP 422. Confirmed live against api.superdocs.app.
- Fix: align the prose with the schema (job_id + change_id), or accept chunk_id as an alias.
