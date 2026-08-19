# Object-storage pipeline (S3 → SuperDocs → S3)

Built for SuperDocs Round 2, Task 2 (assigned build). An S3-compatible
bucket where dropping a file into `incoming/` triggers ingest into
SuperDocs, an edit instruction, review/approval, and export — with the
result written back to `processed/`, all using pre-signed URLs so the
orchestrator process never buffers the file's full contents.

## This version fixes a broken first attempt — read this first

The version of this build submitted earlier was written against a
**guessed API schema** — `POST /documents`, `POST /documents/{id}/chat`,
`POST /documents/{id}/approve`, `GET /documents/{id}/export` — because
`docs.superdocs.app` was reported unreachable from that build
environment. **None of those endpoints exist on the real SuperDocs API**,
which is why it didn't work end to end: every request would have failed
immediately.

This version is rewritten from scratch against the real, documented
REST contract at `docs.superdocs.app`, endpoint by endpoint. See
"How this matches the real API" below for the exact mapping. Along the
way it also found and fixed one more real bug: `pydantic-settings`
raises a validation error at startup if an `Optional[int]`/`Optional[str]`
field is set to an **empty string** in `.env` (as several fields in
`.env.example` were, by design, so they could be left blank) — see
`app/config.py`'s `_blank_env_value_means_unset` validator.

## How this matches the real API

Every field name below is copied verbatim from the documentation
provided with the task, not reconstructed from memory:

| Step | Endpoint | Key request fields | Key response fields |
|---|---|---|---|
| Upload (small file) | `POST /v1/documents/upload` (multipart) | `file`, `session_id` | `session_id`, `chunks_count`, `version_id` |
| Upload (large file) | `POST /v1/uploads` | `filename`, `content_type`, `size_bytes`, `purpose` | `upload_url`, `upload_id` |
| — then PUT the bytes | `PUT {upload_url}` | raw bytes | — |
| — then parse into session | `POST /v1/uploads/{upload_id}/process` | `filename`, `session_id`, `parse_mode="document"`, `return_html=false` | `session_id`, `chunks_count`, `version_id` |
| Edit (start) | `POST /v1/chat/async` | `message`, `session_id`, `approval_mode="ask_every_time"` | `job_id` |
| Edit (poll) | `GET /v1/jobs/{job_id}` | — | `status`, `metadata.pending_changes`, `result` |
| Edit (approve) | `POST /v1/chat/{session_id}/approve` | `job_id`, `approved: true`, `changes: [{change_id, approved}]` | — |
| Export | `POST /v1/documents/export` | `session_id`, `format`, `options` | binary body, `X-Export-Warnings` header |

`app/superdocs_client.py`'s module docstring and inline comments cite
the exact doc section behind each design choice (which endpoint, which
field names, why a given retry/threshold value).

## Why `ask_every_time` + auto-approve, not `approve_all`

Two SuperDocs approval modes both exist and both work:

- **`approve_all`** — a single synchronous `POST /v1/chat` call folds
  the edit and the approval into one round trip. Simpler, fewer calls.
- **`ask_every_time`** — the async `POST /v1/chat/async` → poll → review
  → `POST /v1/chat/{session_id}/approve` → poll sequence. More calls,
  but it's the literal shape of "the minimum contract with us is four
  calls: upload... send an edit instruction... approve the proposed
  changes... export" from the task brief, and it's the workflow the
  product's own pitch centers on ("targeted edits, applied directly in
  the document, reviewed and approved by you").

This build defaults to `ask_every_time`, with every proposed change
auto-approved by the pipeline itself rather than a human — the assigned
card doesn't ask for a human reviewer, so a blocking human gate would be
scope creep, but the *mechanism* (a real approval step, a real decision
per change) is exercised for real rather than skipped. Set
`SUPERDOCS_APPROVAL_MODE=approve_all` in `.env` to use the simpler
single-call path instead — both are implemented and both are tested
(`tests/test_superdocs_client_hitl.py`).

## What "strong" means here, and how it's proven

The card's bar is specific: **never downloads the payload to the
orchestrator, and handles files far past inline limits.** This isn't
asserted — `tests/test_streaming_bounds.py` proves it mechanically
against *both* real upload paths independently:

- A 4 MiB fixture through the **direct multipart** path
  (`POST /v1/documents/upload`), asserting no chunk the orchestrator
  reads ever exceeds the configured bound.
- A 40 MiB fixture through the **pre-signed** path
  (`POST /v1/uploads` → `PUT` → `POST /v1/uploads/{id}/process`), the
  real branch this build takes for files past the direct-upload
  threshold — proving "far past inline limits" is a genuine code path,
  not a claim about a single endpoint that happens to accept anything.
- The export leg, streamed straight to a pre-signed S3 PUT URL, same
  bounded-chunk assertion in the opposite direction.

Multipart encoding is hand-rolled (`app/superdocs_client.py::_multipart_stream`)
rather than relying on `httpx`'s own multipart machinery, specifically
so this streaming behaviour is explicit, testable, and independent of
any particular `httpx` version's handling of generic iterators passed to
`files=`.

## How it works

1. `S3Gateway.list_incoming()` lists new keys under `incoming/` — no
   bytes read, just metadata (including size, which decides the
   upload-path branch below without any extra request).
2. `S3Gateway.presigned_get()` produces a pre-signed URL for that key.
3. The pipeline opens that URL as a streaming HTTP response and hands
   the byte iterator straight to `SuperDocsClient.upload_document()`,
   which picks the direct or pre-signed upload path based on the
   object's size (`SUPERDOCS_DIRECT_UPLOAD_MAX_BYTES`, default ~15 MB,
   safely under the ~20 MB direct-multipart ceiling the docs describe).
   The file streams S3 → SuperDocs through the orchestrator's process
   without ever being fully materialized as one in-memory object.
4. `SuperDocsClient.edit_document()` sends the configured instruction
   (default: reformat + fix heading hierarchy, preserving every fact and
   figure) and runs it through to completion — either one `approve_all`
   call, or the full async/poll/approve/poll sequence with every change
   auto-approved (see above).
5. `SuperDocsClient.export_to_dest_url()` streams the exported file
   straight from SuperDocs to a pre-signed S3 PUT URL — same
   no-full-buffering property, opposite direction. Because export is
   driven by `session_id` (not inline HTML), there's no size limit on
   this side either: SuperDocs already holds the document server-side.
6. `S3Gateway.mark_processed()` moves the source object to
   `processed/source/` so the poller never reprocesses it.

Polling (`app/cli.py watch`) checks the bucket every few seconds rather
than using S3 Event Notifications + SQS. That's a deliberate scope
decision, not an oversight — event notifications need account-specific
SQS/IAM wiring that can't be meaningfully demonstrated in a
self-contained repo a reviewer clones and runs. `Pipeline.process_new_objects()`
doesn't know or care how it was triggered, so swapping to
SQS-driven invocation later is a deployment change, not a rewrite.

## Supported formats and domains

Upload accepts exactly the formats `POST /v1/documents/upload` supports:
`.docx`, `.doc`, `.odt`, `.pdf`, `.txt`, `.html`, `.htm`, `.md`, `.rtf`
(see `app/util.py::SUPPORTED_UPLOAD_EXTENSIONS`). Anything else dropped
into `incoming/` is skipped with a warning and left in place — never
silently deleted — so a human can deal with it
(`tests/test_pipeline.py::test_unsupported_extension_is_skipped_and_left_for_a_human_not_silently_dropped`).
Export accepts `docx`, `pdf`, `html`, `markdown`, `txt`
(`SUPERDOCS_EXPORT_FORMAT`, default `pdf`). No domain restriction — the
default edit instruction is deliberately generic (reformat + fix
headings, preserve every fact/figure); point `SUPERDOCS_EDIT_INSTRUCTION`
at whatever your document type needs (a specific compliance reformat, a
specific style guide, etc.) with no code change. A second run means
different documents inside this same declared set — nothing in the code
path is fixture-specific.

## What's honestly thinner

- **No human-approval UI on the edit itself** — every proposed change is
  auto-approved by the pipeline. The card doesn't ask for a human
  reviewer; if this pipeline needed one, the `ask_every_time` path
  already surfaces `metadata.pending_changes` at exactly the point
  where a human decision could be inserted instead of the automatic
  approve-all call in `SuperDocsClient._approve_all_pending`.
- **The `purpose` value sent to `POST /v1/uploads` for large-file
  ingestion is a logged assumption** (`document-upload`). The
  documentation's only worked example of this field
  (`purpose="export-html"`) is for a different use — re-uploading HTML
  before exporting an oversized document — and gives no example value
  for ingesting a brand-new source file this way. Isolated to one
  config value (`SUPERDOCS_UPLOAD_PURPOSE`) — a one-line fix if the live
  value differs.
- **Failure handling is retry-by-leaving-in-place**, not a dead-letter
  queue: a file that fails processing simply stays in `incoming/` and is
  retried on the next poll
  (`tests/test_pipeline.py::test_a_failure_on_one_file_does_not_block_or_lose_the_others`
  proves other files aren't blocked by one failure). A production
  version at real volume would want a max-retry count and a
  dead-letter prefix (`S3_FAILED_PREFIX` is reserved in config for this,
  not yet wired up); not built here since nothing in the card asks for
  it and it would be speculative without a real failure mode to design
  against.
- **429/5xx retries use a fixed exponential backoff**, not the
  documented distinction between "quota exhausted" (wait until billing
  reset — often not worth retrying automatically) and "infrastructure
  surge" (retry with jitter). `SuperDocsClient._request` retries both
  the same way, bounded by `SUPERDOCS_MAX_RETRIES`; a production version
  would branch on the `X-Usage-*` headers to fail fast on quota
  exhaustion instead of retrying into a wall.

## Running it

Against MinIO (fully local, no AWS account needed):

```bash
docker compose up -d
cp .env.example .env   # edit SUPERDOCS_API_KEY
pip install -e ".[dev]"
python -c "from app.cli import _build_pipeline; _build_pipeline()"  # creates the bucket
```

Drop a file in and process it once:

```bash
aws --endpoint-url http://localhost:9000 s3 cp mycontract.pdf s3://vendor-docs/incoming/
python -m app.cli run-once
```

Or run the poller continuously, optionally capped for testing:

```bash
python -m app.cli watch --limit 2   # process at most 2 files per pass
```

Against real AWS S3: unset `S3_ENDPOINT_URL`, set real `AWS_ACCESS_KEY_ID`
/ `AWS_SECRET_ACCESS_KEY` (or use an IAM role), point `S3_BUCKET` at a
real bucket. No code changes.

## Tests (no live key, no network, no MinIO required)

```bash
pip install -e ".[dev]"
pytest -v
```

23 tests, all offline:

- `test_s3_client.py` — bucket creation, listing, pre-signed URL
  generation, and the processed-move, all against `moto`'s in-memory S3
  mock.
- `test_pipeline.py` — full sequencing (`upload → edit → export`)
  against a fake SuperDocs client and real moto S3, including
  multi-file batches, one-file-fails-doesn't-block-the-rest, unsupported
  extensions being skipped (not deleted), and the `max_files_per_run`
  operations-budget cap.
- `test_streaming_bounds.py` — the core claim, proven mechanically
  against both real upload paths (direct multipart under the size
  threshold, pre-signed over it) and the export path, against
  `httpx.MockTransport`.
- `test_superdocs_client_hitl.py` — the real async/poll/approve/poll
  sequence, the `continue_prompt` pause handled distinctly from a change
  review, a failed job raising a clear error rather than a silent
  success, and the `approve_all` single-call alternative.
- `test_util.py` — session-id sanitizing against SuperDocs' documented
  charset rule, supported-format detection, content-type mapping.
