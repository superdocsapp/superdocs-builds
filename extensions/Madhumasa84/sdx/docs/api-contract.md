# Verified SuperDocs API contract

Verified: **2026-08-06** against the current documentation and public OpenAPI document. No authenticated or billable request was used to establish this contract.

## Sources consulted

- <https://docs.superdocs.app/llms.txt>
- <https://docs.superdocs.app/llms-full.txt>
- <https://api.superdocs.app/openapi.json>
- <https://docs.superdocs.app/concepts/documents>
- <https://docs.superdocs.app/guides/async-jobs>
- <https://docs.superdocs.app/guides/human-in-the-loop>
- <https://docs.superdocs.app/guides/agent-editing-playbook>
- <https://docs.superdocs.app/errors/error-codes>
- <https://docs.superdocs.app/errors/rate-limits>
- <https://docs.superdocs.app/examples/javascript>

The production REST base URL is `https://api.superdocs.app`. API routes below require `Authorization: Bearer <SUPERDOCS_API_KEY>` unless explicitly identified as signed storage. JSON requests also require `Content-Type: application/json`.

## Document ingestion

### Request a pre-signed upload

- Method/path: `POST /v1/uploads`
- Body: `filename` (including supported extension), `content_type`, positive `size_bytes` up to 104,857,600, and `purpose: "document"`.
- Relevant response: `upload_id`, `upload_url`, `expires_at`, `expires_in_seconds`, `max_size_bytes`, `curl_example`.
- The signed URL is documented as valid for five minutes. `upload_id` is opaque.

### Stream bytes to signed storage

- Method/target: `PUT` to the exact `upload_url` returned above.
- Headers: the requested `Content-Type`; `Content-Length` when known.
- Authentication invariant: never send the SuperDocs `Authorization` header to this URL. The signed query string is the storage credential and must be redacted from logs/errors.
- Body: original file bytes as a stream. No Base64 and no whole-file buffering.
- Success: any successful storage response; it has no required JSON body.

### Parse the uploaded object

- Method/path: `POST /v1/uploads/{upload_id}/process`
- Body: `session_id`, the same `filename`, `parse_mode: "document"`, `return_html: false`.
- Relevant response: required `session_id`, `filename`, `status`, `parse_mode`; optional/nullable `html`, `chunks_count`, `version_id`, `job_id`, `page_setup`, `warnings`.
- Verification: the response session, filename, and parse mode must match the request before editing begins.

The parse operation loads the document into the session. Therefore the subsequent chat request does not resend `document_html`.

## Async review workflow

### Start an edit

- Method/path: `POST /v1/chat/async`
- Body used by `sdx`: `message`, `session_id`, `approval_mode: "ask_every_time"`, `response_mode: "full"`.
- Relevant response: `job_id`, `session_id`, initial `status: "pending"`, optional message.
- `job_id` and `session_id` are opaque strings.

### Poll the job

- Method/path: `GET /v1/jobs/{job_id}`; optional `compact` query exists but Stage 2 uses the default full response.
- Relevant required fields: `job_id`, `session_id`, `job_type`, `status`, `created_at`, `updated_at`, `progress`.
- Relevant optional fields: `result`, `error`, and `metadata`.
- States: `pending` → `in_progress` → `awaiting_approval` (zero or more rounds) → `completed`; terminal failures are `failed` and `cancelled`.
- Polling is bounded by an overall timeout and supports cancellation.

### HITL proposed changes

For a normal review pause, `metadata.pending_changes` contains changes with required `change_id` and `operation` (`edit`, `create`, or `delete`) plus nullable/optional `chunk_id`, `document_id`, `old_html`, `new_html`, and `ai_explanation`.

Some event/fixture-derived payloads carry JSON-encoded content inside an already-decoded JSON response. `sdx` supports normal objects, encoded objects, and encoded batch objects, performs at most the documented second parse, and treats malformed or missing required data as exit 25.

### Submit item decisions

- Method/path: `POST /v1/chat/{session_id}/approve`
- Batch body: `job_id`, required top-level `approved`, and `changes: [{ change_id, approved, feedback? }]`.
- Every `sdx` entry carries its own explicit `approved` value. The top-level value remains required even when every item overrides it.
- Relevant success response: an object; the published OpenAPI success schema is otherwise unconstrained.
- After submission, poll the same job until a new review round or a terminal state.

### Continue or stop a large edit

When `status` is `awaiting_approval` and `metadata.awaiting_kind` is `continue_prompt`, read `metadata.continue_prompt` (`message`, optional progress counts). Do not call the approval endpoint.

- Method/path: `POST /v1/chat/{session_id}/continue`
- Body: `job_id`, `continue: true|false`.
- `true` resumes with a fresh work budget. `false` stops while retaining already-completed work. The job can pause again, so polling continues until terminal.
- Calling `/approve` for a continuation pause, or `/continue` for HITL review, is documented to return 409.

## Export and download

### Direct export

- Method/path: `POST /v1/documents/export`
- Body used for a session export: `session_id`, `format`; optional `options` and filename fields.
- Formats: `docx`, `pdf`, `html`, `markdown`, `txt`; legacy `doc` is not selected by `sdx`.
- Success is a binary response with `Content-Type` and `Content-Disposition`. `X-Export-Warnings`, when present, is a Base64-encoded JSON warning list. This header encoding is metadata only; document bytes are never Base64-encoded by `sdx`.

### Request a signed download

The Stage 2 vertical slice selects the agent-friendly signed path so exported bytes do not traverse a JSON response.

- Method/path: `POST /v1/downloads`
- Body: required `session_id`, selected `format`, optional `filename`/`options`.
- Relevant response: `download_url`, `expires_at`, `expires_in_seconds`, `curl_example`, `filename`, `format`.
- The download URL is documented as valid for 15 minutes.

### Stream and finalize download

- Method/target: `GET` the exact `download_url` with no SuperDocs authorization header.
- Stream into an exclusive temporary file in the destination directory.
- Require a non-empty temporary file, then finalize it atomically.
- Remove temporary output on every controllable failure. Default exclusive finalization uses a same-directory hard link plus unlink; explicit overwrite uses atomic rename. The default destination uses `.sdx.<format>` and cannot overwrite the source.

## Authentication, errors, and rate metadata

Stage 2 reads authentication only from `SUPERDOCS_API_KEY`; there is no CLI key option. Missing or HTTP 401 authentication maps to exit 20 before false success.

Published API errors normally contain JSON with `detail`, but gateway 413 and infrastructure 429 responses may be HTML/plain text. `sdx` safely captures only a bounded, redacted error body. Mapping:

- 401 → exit 20
- 429 → exit 21
- other API HTTP/transport errors → exit 22
- signed upload/local read failure → exit 23
- export/download/write failure → exit 24
- successful but schema-invalid JSON → exit 25

Preserved safe metadata includes HTTP status, `X-Request-Id`/`Request-Id`, `Retry-After`, `X-Usage-Limit`, `X-Usage-Used`, and `X-Usage-Remaining`. Stage 4 retry classification is below and in `docs/retry-recovery.md`.

## Ambiguities and mismatches

1. The Documents concept guide foregrounds synchronous multipart `POST /v1/documents/upload`, whereas the current full reference and OpenAPI contract additionally document the pre-signed `POST /v1/uploads` → PUT → `POST /v1/uploads/{upload_id}/process` path for editable documents. Stage 2 follows the latter, exact OpenAPI-backed contract.
2. The OpenAPI `JobMetadata` schema allows additional fields and does not enumerate `awaiting_kind`/`continue_prompt`, while the async/HITL guides require both. `sdx` validates the documented fields explicitly while allowing unrelated metadata.
3. Approval and continuation success responses are objects with unconstrained published schemas. `sdx` verifies that they are JSON objects, then relies on subsequent job polling for actual completion.
4. Direct export is binary even though its OpenAPI 200 content entry is represented generically. The Documents guide is authoritative for binary headers/body. The Stage 2 CLI uses `/v1/downloads` for its tested vertical slice.
5. Contract-derived local fixtures are deterministic and sanitized but are not claimed to be recorded production responses.

## Stage 3 verified session and creation additions

Verified again on **2026-08-06** against the current public OpenAPI plus:

- <https://docs.superdocs.app/concepts/sessions>
- <https://docs.superdocs.app/concepts/files>
- <https://docs.superdocs.app/concepts/documents>
- <https://docs.superdocs.app/guides/multi-document>
- <https://docs.superdocs.app/guides/model-selection>

### Durable named-session reuse

The caller chooses `session_id`; the current OpenAPI constrains it to letters, digits, underscore, hyphen, and dot, at most 256 characters. The Sessions guide states that reusing it resumes conversation and document state, that the document need not be resent after the first load, and that sessions persist until explicitly retired. Stage 3 therefore stores a local alias -> server ID mapping and sends later `/v1/chat/async` turns without upload or `document_html`.

The Files guide states that uploaded/created documents become durable Files and that a File outlives a session. Current multi-document docs distinguish a session-local `document_id` from a permanent `durable_document_id`. The pre-signed `ProcessDocumentResponse` OpenAPI schema does not require either field, so `sdx` treats both as optional additive metadata and never fabricates one. The stored source path and SHA-256 protect against silently replacing the focused remote document.

`POST /v1/chat/async` also documents optional `model_tier` and `document_id`. Stage 3 passes a validated profile-selected model tier and targets a stored document ID only when one was actually returned.

### Creating from supplied text

The current Async Chat contract warns that exact content already held by the caller should be loaded verbatim rather than described for AI re-authoring. For `sdx new [file]` and stdin, Stage 3 uses the already verified pre-signed `purpose: "document"` upload/process path with a sanitized title-derived filename, then exports the loaded session. This preserves supplied Markdown/TXT/HTML exactly and does not create an approval-bypassing AI turn. It is distinct from the documented “message to an empty session” AI-authored from-scratch flow, which would require its own instruction/review UX.

### Local-only operations

Profiles, credentials, aliases, completions, and doctor add no SuperDocs endpoint. `sessions remove` never calls session deletion, File archive, or close endpoints. Doctor intentionally performs no account/health request because no required, API-key-safe health schema is published in the OpenAPI; it validates the configured URL locally and consumes zero document operations.

### Stage 3 contract caveats

1. Process responses may acquire optional document IDs, but the current OpenAPI does not require them; named reuse relies on the documented server session ID.
2. File title is represented to the upload path by the sanitized source filename. Stage 3 does not call rename/archive APIs.
3. Remote cancellation remains unsupported and is not implied by durable pending-job metadata.

## Stage 4 resilience findings

Verified again on **2026-08-06** against the current public OpenAPI plus:

- <https://docs.superdocs.app/errors/rate-limits>
- <https://docs.superdocs.app/errors/error-codes>
- <https://docs.superdocs.app/guides/async-jobs>
- <https://docs.superdocs.app/guides/human-in-the-loop>
- <https://docs.superdocs.app/openapi.json>

### Application and infrastructure 429

The rate-limit guide identifies application 429 as a JSON response with `Retry-After` in seconds. `sdx` branches on status/header, waits no less than that value only when it fits the remaining command/attempt budget, and otherwise fails promptly. Usage headers remain safe structured error metadata. A conclusively rejected 429 may be repeated even for a write because the server did not accept it.

The same guide identifies transient infrastructure 429 as potentially plain text without `Retry-After`. Only status 429 plus absent header plus non-JSON content enters bounded exponential full-jitter backoff. Arbitrary HTML/plain errors are not reclassified as rate limits.

The error-code guidance documents 500/502/503 as transient classes. `sdx` retries them—and ambiguous transport failures—only for read-only operations and atomic signed downloads. Upload, parse, approval, continuation, export-URL, and chat writes do not retry after ambiguous transport/5xx outcomes. Signed uploads also do not retry because repeating an accepted PUT is not explicitly guaranteed safe by the current contract.

### No documented idempotency mechanism

The inspected OpenAPI (version 2.0.0, 77 paths) contains no documented `Idempotency-Key`, idempotency header, or request-identifier input for the endpoints used here. `sdx` sends none. It writes local state before chat submission and blocks resubmission if acceptance becomes unknown. This provides at-most-one **automatic** chat submission per local operation, not exactly-once delivery.

`GET /v1/jobs` is documented, but its available metadata does not bind a result to the CLI's privacy-safe request fingerprint. `sdx` therefore does not reconcile an unknown submission by guessing from timing, session membership, or instruction content.

### Job retention and same-job recovery

The async-job guide says jobs expire after one hour and recommends persisting the job ID. `sdx resume [job-id]` polls only the persisted ID through repeated HITL/continuation rounds. A 404 becomes an expired/unretained error and never triggers a replacement edit. Resume never calls `/v1/chat/async`.

Pending export intent stores format/path, not a signed URL. If completion preceded interruption, resume calls the documented `/v1/downloads` endpoint for a fresh 15-minute signed URL and performs a new atomic signed GET. Interrupted uploads likewise never persist/reuse their five-minute signed URL; an explicit later upload must acquire a fresh URL through `POST /v1/uploads`.

### Contract-derived versus live-recorded fixtures

Stage 4 adds a sanitized recorder/replayer, but no environment key was present. The checked-in cassette remains explicitly contract-derived and is not represented as live traffic. A genuinely live cassette and live 120-page run remain external verification gaps with zero Stage 4 billable operations performed here.
