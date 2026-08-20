# SuperDocs contract record — 2026-08-13

Source: official `superdocsapp/docs` OpenAPI and examples. Authentication is `Authorization: Bearer <SUPERDOCS_API_KEY>`. This build requires the server-side base URL to be exactly `https://api.superdocs.app`.

The build uses `upload_document_base64`, `chat_async` in `ask_every_time` mode, `get_job`, per-change HITL approval, and `export_document`. Polling is bounded and terminates on `awaiting_approval`, `completed`, or `failed`. Proposed changes may be an array or a JSON-encoded string and are schema-checked after the optional second parse.

Live observation on 2026-08-15: replaying an identical approval after the first successful submission returned HTTP 400. The application therefore fingerprints a reviewed decision payload and suppresses an identical repeat instead of replaying it upstream. This is application-level idempotency; the hosted approval endpoint is not claimed to be replay-idempotent.

Current OpenAPI location: while status is `awaiting_approval`, proposals are
`metadata.pending_changes`; completed compact responses may expose
`result.document_changes.pending_changes` or `chunk_diffs`. Each `PendingChange` uses
`change_id`, `old_html`, and `new_html`. Any other shape fails visibly. Export bytes are not
considered valid merely because the HTTP request succeeded; live verification must inspect
non-empty content/type and expected sections.

This submission exports and claims HTML only. The client-ready and file-ready variants are generated from the same reviewed state before each HTML export request.
