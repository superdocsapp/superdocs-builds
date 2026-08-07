# Retry, ledger, restart, and locking

## Retry classification

All API operations use one central policy. Defaults are four total attempts, a 250 ms exponential base, a 5,000 ms delay cap, and full jitter uniformly selected from zero through `min(5000, 250 * 2^(attempt-1))` milliseconds. The policy clock, sleeper, randomness, base/cap, and attempt limit are injectable; deterministic tests use fake time and never sleep.

| Failure | Read-only GET / atomic signed download | Signed upload | Non-billable write | Async chat submission |
|---|---|---|---|---|
| Application 429 with valid `Retry-After` | Retry only inside attempts/command budget | Same, because the server conclusively rejected the attempt | Same | Same |
| Infrastructure 429, non-JSON, no `Retry-After` | Bounded full-jitter retry | Same, because the server conclusively rejected the attempt | Same | Same |
| 500/502/503 response | Bounded full-jitter retry | No | No | No |
| Connection reset/timeout/ambiguous transport | Bounded full-jitter retry | No | No | No |
| Other HTTP, malformed JSON, partial body | Fail safely | Fail safely | Fail safely | Fail safely |

An application 429 never retries before the documented delay. When that delay exceeds the remaining command budget, `sdx` fails immediately and reports status, retryability, `retryAfterSeconds`, safe usage headers, and attempt count in JSON error details. Infrastructure 429 classification requires status 429, absent `Retry-After`, and a non-JSON content type; arbitrary non-JSON errors are not treated as rate limits.

Signed downloads are repeatable because every attempt writes to an exclusive temporary file and only a complete non-empty transfer can be finalized. Signed uploads are not retried after an ambiguous transport failure because repeating the upload is not documented as safe. No state-changing 500/transport failure is blindly retried.

## Idempotency and unknown remote state

The public OpenAPI inspected on 2026-08-06 documents no `Idempotency-Key` or equivalent request identifier for the endpoints used by `sdx`. The CLI does not invent or send one and does not claim exactly-once delivery.

Before `/v1/chat/async`, `sdx` durably writes a privacy-safe operation record and transitions it to `submission-started`. Immediately after a response, it stores `acknowledged` plus `job_id` before polling. If the connection fails while the submission outcome is ambiguous, the operation becomes `unknown`, exit 22 is returned, and the same session is blocked from automatic resubmission. The current job-list response does not expose a reliable client request fingerprint, so `sdx` does not guess by timing or session membership. Manual reconciliation is required.

The practical guarantee is **at-most-one automatic chat submission per local operation**, not exactly-once server execution. A connection may fail after the server accepted the only submission but before the client learned its job ID.

## Operation ledger

`~/.sdx/operations.json` is versioned JSON, atomically replaced at mode 0600 inside a 0700 state directory. It stores:

- a random operation ID;
- SHA-256 fingerprints of stable source/instruction inputs (never the raw instruction);
- canonical source path, filename, media type, byte count, and source SHA-256;
- safe session, upload, document, and job IDs when known;
- requested export format/path and timestamps;
- lifecycle state.

States are `prepared`, `upload-prepared`, `upload-completed`, `document-processed`, `submission-started`, `acknowledged`, `waiting-approval`, `waiting-continuation`, `approval-decided`, `continuation-decided`, `completed`, `terminal`, `export-requested`, `download-completed`, `unknown`, and `failed`. Decision states are durable before the approval/continuation request, so restart recovery can deny an applied completion that has no local proof of an explicit user decision.

Signed URLs, signed queries, document bytes, raw instructions, API keys, and authorization headers are never persisted. Upload checkpoints retain the opaque `upload_id`, not the signed URL. An interrupted signed upload is not replayed: a future explicit workflow must obtain a fresh URL through documented `POST /v1/uploads`. Pre-chat checkpoints make the boundary diagnosable, but `sdx resume` does not recreate a private instruction that was intentionally never stored.

## Restart recovery

`sdx resume [job-id]` operates only on persisted acknowledged jobs and never submits `/v1/chat/async`. Without an ID it selects a single pending job, optionally filtered by `--session`; multiple matches are listed and require explicit selection.

Resume polls the same job through repeated review and continuation rounds. Approval remains explicit: without `--approve`, an actionable review exits 3; with it, every item or continuation is prompted again. If completion happened before termination, resume requests a fresh signed export URL and atomically downloads the saved export intent. It never persists or reuses signed URLs. A 404 is treated as expired/unretained state and reports that no replacement edit was submitted.

Ctrl+C aborts local work, preserves ledger and pending-job records, removes controllable temporary files, exits 130, and never claims remote cancellation. SIGKILL cannot run cleanup; the next atomic download removes orphan temporary files only when their recorded owner PID is dead.

## Concurrency model

Every profile, credential, session, pending-job, and ledger read-modify-write holds an inter-process lock implemented by atomic lock-directory creation. Lock directories and owner records are 0700/0600. Acquisition waits at most two seconds by default. A lock is recoverable when the recorded PID is dead, or when incomplete owner metadata exceeds the 30-second stale threshold.

Named edit/new/approve/resume commands also hold a SHA-256-derived per-session workflow lock. Two processes targeting one alias cannot create duplicate chat work; different aliases have independent locks and remain concurrent. All state updates use same-directory atomic replacement, preserving 0600 permissions and preventing lost updates.

## JSON and secrets

Retry and unknown-state metadata are backward-compatible contents of the existing `error.details` field; schema version remains `1.0`. JSON stdout remains exactly one object. Retry diagnostics go only to stderr. Messages and metadata are bounded and redacted; credentials, signed URLs, and private document content are excluded.
