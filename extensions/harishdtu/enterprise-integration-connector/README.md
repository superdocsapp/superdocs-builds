# SuperDocs Enterprise Integration-Platform Connector

A production-quality connector that exposes SuperDocs' document generation,
editing, human-approval, and export workflow as typed, first-class operations
for enterprise integration platforms (Workato, Tray.io, Boomi, MuleSoft).

Built for SuperDocs Round 2, Task 2 — "Your assigned build: Enterprise
integration-platform connector."

> **Not certified with any platform.** This connector has not been submitted
> to or run through Workato's, Tray's, Boomi's, or MuleSoft's own connector
> certification process. It is structured to be *adaptable* to each — see
> [Callback architecture](#11-callback-architecture) — but "certified" is not
> claimed anywhere in this repository.

---

## 1. Purpose

SuperDocs' native API is a chat-and-poll interface: you send a natural-language
instruction to a session, poll a job until it resolves, and optionally approve
proposed changes along the way. That's a good fit for a conversational agent.
It's a poor fit for a drag-and-drop integration-platform recipe builder, which
expects **discrete, typed operations with explicit inputs/outputs**: "upload a
document," "wait for approval," "export as PDF" — not "manage a chat session."

This connector is the adapter layer between those two worlds.

## 2. Supported platforms / conceptual integration model

The connector itself is plain, dependency-light Python (`httpx` + `pydantic`)
with no platform SDK baked in. It exposes:

- A typed **operations** layer (`connector/operations/`) any platform's
  custom-code/script step can call directly.
- A **callback** abstraction (`connector/callbacks.py`) with named adaptation
  points (`WorkatoCallbackDispatcher`, `TrayCallbackDispatcher`,
  `BoomiCallbackDispatcher`, `MuleSoftCallbackDispatcher`) — each documents
  *how* that platform resumes a paused recipe from an inbound webhook, since
  all four share the same underlying pattern (a stable inbound URL a paused
  flow resumes from), just with different auth conventions on that inbound
  hook.

Wrapping this in an actual Workato custom connector manifest, a Tray
connector's node definitions, etc. is platform-specific packaging work left
to whoever adapts this for a specific platform — this repository provides the
verified, tested core those wrappers would call into.

## 3. Architecture

```
recipes/            <- 3 reference recipes (see section 15), the top-level
                        demonstration of "how a platform actually uses this"
    |
    v
connector/operations/  <- one typed function per platform-facing operation:
    |                      generate_from_template, edit_by_instruction,
    |                      submit_for_approval, poll_for_completion,
    |                      export_document, upload_document
    v
connector/worker.py  <- job-status polling loop (configurable backoff/jitter/
    |                    timeout) + background-task orchestration
    v
connector/callbacks.py <- delivers a typed event to the platform's own
    |                      webhook once a job reaches a terminal state
    v
connector/http_client.py <- the one place that talks to api.superdocs.app:
    |                         auth injection, retry contract, error mapping
    v
schemas/             <- pydantic input/output models for every operation
connector/errors.py  <- typed error hierarchy, one class per HTTP-status
                         category, each carrying `retryable: bool`
connector/config.py  <- ConnectorConfig: base URL, timeouts, retry/poll/
                         callback tuning, all overridable, zero hardcoded
                         secrets
```

Each layer only talks to the layer directly below it. `connector/operations/`
never touches `httpx` directly; `connector/http_client.py` never knows what a
"pending change" is (that's a schemas/ concept it just deserializes into).

## 4. Authentication

```python
from connector import ConnectorConfig

config = ConnectorConfig(api_key=os.environ["SUPERDOCS_API_KEY"])
```

- Sent as `Authorization: Bearer <key>` on every SuperDocs API call
  (`connector/http_client.py`).
- Accepts both personal (`sk_...`) and org-scoped (`lce_...`) key prefixes;
  `ConnectorConfig.__post_init__` validates the prefix and rejects an empty
  key immediately, before any network call.
- `ConnectorConfig.redacted()` / `__repr__` never print the full key —
  useful for logging the config object safely.
- The key is **never** sent to the pre-signed-upload cloud-storage URL (see
  §5) — `SuperDocsHTTPClient.put_presigned` deliberately uses a separate,
  unauthenticated HTTP client for that one call.
- Recommended env var: `SUPERDOCS_API_KEY` (matches the convention used
  elsewhere in this monorepo's task documents).

## 5. Upload

`connector.operations.upload_document` picks a strategy by file size rather
than always base64-encoding:

| Size | Strategy | Calls |
|---|---|---|
| ≤ 100KB (SuperDocs' own documented "still works inline" threshold) | inline base64 | `POST /v1/documents/upload-base64` |
| > 100KB, up to 100MB | pre-signed URL | `POST /v1/uploads` → `PUT <upload_url>` → `POST /v1/uploads/{id}/process` |

`force_presigned=True` routes any size through the pre-signed path (mainly
useful for testing that path deterministically). Legacy `.doc` is rejected
client-side with a clear message before any HTTP call — SuperDocs doesn't
support it; convert to `.docx` first.

## 6. Generate from template

**There is no dedicated SuperDocs template-fill endpoint.** This was verified
against SuperDocs' OpenAPI reference before writing a single line of this
operation, and the assignment brief itself confirms it. `generate_from_template`
is a connector-level composition, not a 1:1 endpoint wrapper:

```
template_reference (template_id | inline_base64+filename | by_name)
        |
        v
[inline_base64 only] upload_document  -- loads the template as the session's document
        |
        v
POST /v1/chat/async  -- natural-language generation instruction, template
                         reference woven into the instruction text for the
                         template_id/by_name cases
        |
        v
job_id returned immediately (see §9 — this never blocks)
```

`by_name` is the least reliable option — it leans on SuperDocs' own semantic
template search inside the chat flow, which this connector has no way to
verify deterministically. `template_id` and `inline_base64` are more precise.

## 7. Edit by instruction

Async-first by design. `EditByInstructionInput.run_async` defaults to `True`.
Sync (`POST /v1/chat`) is available for genuinely short edits where blocking a
worker for a few seconds is acceptable — but `approval_mode="ask_every_time"`
**requires** `run_async=True` and is rejected client-side (before any HTTP
call) if combined with `run_async=False`, since a HITL pause cannot happen
synchronously.

## 8. Approval

The single most important correctness detail in this connector, called out
explicitly in the brief:

> The top-level `approved` field is mandatory, even for batch decisions.

`connector/operations/submit_for_approval.py` builds the request body from
`ApprovalInput` and **always** includes top-level `approved`, in all three
supported shapes:

```python
# Single
ApprovalInput(session_id=s, job_id=j, approved=True, change_id="c1")
# -> {"job_id": j, "approved": true, "change_id": "c1"}

# Batch, same decision for all
ApprovalInput(session_id=s, job_id=j, approved=True, change_ids=["c1","c2"])
# -> {"job_id": j, "approved": true, "changes": [{"change_id":"c1"},{"change_id":"c2"}]}

# Batch, per-change decisions
ApprovalInput(session_id=s, job_id=j, approved=False,
              changes=[ChangeDecision(change_id="c1", approved=True),
                       ChangeDecision(change_id="c2", approved=False)])
# -> {"job_id": j, "approved": false, "changes": [{"change_id":"c1","approved":true}, ...]}
```

`ApprovalInput` validates that exactly one of `change_id` / `change_ids` /
`changes` is set — the three shapes are mutually exclusive.
`tests/test_approval.py::test_top_level_approved_field_is_always_present_regression`
is an explicit regression test for this, per the assignment's own instruction.

### The `awaiting_kind` distinction

`status == "awaiting_approval"` means two different things depending on
`metadata.awaiting_kind`:

| `awaiting_kind` | Meaning | Correct next call |
|---|---|---|
| absent / `"change_review"` | Normal HITL — proposed changes are waiting for a decision | `POST /v1/chat/{session_id}/approve` |
| `"continue_prompt"` | A large edit paused partway through and needs a "yes, keep going" | `POST /v1/chat/{session_id}/continue` |

`PollOutput.awaiting_kind` (an `AwaitingKind` enum) makes this explicit and
type-checked rather than a string a caller has to remember to compare
correctly. Calling `/approve` on a `continue_prompt` job (or vice versa)
returns `409`, mapped to `ConflictError`.

## 9. Polling

`connector/worker.py::poll_until_terminal` is the only polling loop in the
codebase. Configurable via `ConnectorConfig`:

| Field | Default | Meaning |
|---|---|---|
| `poll_initial_interval_seconds` | 2.0 | First poll delay |
| `poll_max_interval_seconds` | 30.0 | Delay ceiling |
| `poll_backoff_factor` | 1.5 | Growth rate per attempt |
| `poll_jitter_ratio` | 0.2 | ±20% randomization, so many concurrent recipe workers don't hammer SuperDocs in lockstep |
| `max_poll_seconds` | 3300 (55 min) | Give up and raise a typed timeout — stays safely under SuperDocs' ~1-hour job GC window |

Terminal states: `completed`, `failed`, `cancelled`, **and** `awaiting_approval`
— the poll loop stops and hands control back the moment there's something for
a human to decide, rather than continuing to poll uselessly past it (per the
brief's explicit instruction).

REST polling, not SSE, is the primary (and only implemented) async mechanism.
See [§18 SSE](#18-why-no-sse) for why.

## 10. Export

`POST /v1/documents/export` returns **raw file bytes**, not a JSON wrapper —
verified against the docs' own curl examples (`--output document.docx`).
`export_document` reads the response body directly, extracts `filename` from
`Content-Disposition` and `content_type` from the `Content-Type` header, and
base64-encodes the bytes into `ExportOutput.content_base64` for JSON-safe
transport through a typed schema (integration-platform recipe steps pass JSON
between nodes, not raw bytes).

`X-Export-Warnings` is parsed defensively — see the honesty note in
`connector/operations/export_document.py::_extract_warnings`'s docstring:
the docs confirm this header exists and is non-fatal, but not its exact wire
encoding. The parser tries base64-JSON, then plain JSON, and falls back to
preserving the raw header text as a single warning rather than silently
dropping it if neither decoding works. **Warnings never turn a successful
export into an error** — `export_document` never raises because of them.

## 11. Callback architecture

**SuperDocs does not provide a native push webhook.** It offers polling, SSE,
and (org-key-only) long-poll — the connector chooses polling as primary (§9)
and builds its own callback layer on top, because integration-platform
recipes need a "resume me when this is done" mechanism SuperDocs itself
doesn't provide.

```
Platform recipe calls generate_from_template / edit_by_instruction (async)
        |
        v
Returns job_id immediately -- the initiating call NEVER blocks on job completion
        |
        v
JobWorker.start_background(job_id, dispatcher) -- fire-and-forget asyncio task
        |
        v
poll_until_terminal (§9's backoff loop)
        |
        +-- completed --------> dispatcher.dispatch(JobCallbackEvent(status="completed", ...))
        +-- failed -----------> dispatcher.dispatch(JobCallbackEvent(status="failed", ...))
        +-- awaiting_approval -> dispatcher.dispatch(JobCallbackEvent(status="awaiting_approval",
        |                                             pending_changes=[...]))  -- platform shows
        |                                             a human the changes, then calls
        |                                             submit_for_approval + starts a fresh
        |                                             background poll (recipe 2 demonstrates this)
        +-- cancelled --------> dispatcher.dispatch(...)
```

`WebhookCallbackDispatcher` POSTs a JSON payload to a platform-supplied URL,
with **bounded retry** (`callback_max_attempts`, exponential backoff +
jitter, all in `ConnectorConfig`) for transient delivery failures — a
webhook endpoint being briefly unreachable during a platform-side deploy is
common and shouldn't be treated as fatal on the first attempt. A definitive
4xx (misconfigured URL) fails fast rather than burning the whole retry budget.

**Critical isolation guarantee**: the SuperDocs job's own outcome is fully
resolved (via `poll_until_terminal`) *before* callback dispatch is ever
attempted. If callback delivery then fails completely
(`CallbackDeliveryError`), `JobWorker.start_background`'s task wrapper catches
and logs it — it never raises into the caller, and it can never retroactively
change what the SuperDocs job's real status was. See
`tests/test_callbacks.py::test_callback_delivery_failure_does_not_corrupt_superdocs_job_state`.

`WorkatoCallbackDispatcher` / `TrayCallbackDispatcher` / `BoomiCallbackDispatcher`
/ `MuleSoftCallbackDispatcher` are named, documented subclasses of
`WebhookCallbackDispatcher` — each docstring explains that platform's actual
resume mechanism (Workato webhook trigger, Tray Wait-for-Webhook step, Boomi
AtomSphere Listener, MuleSoft Anypoint HTTP Listener) and typical auth
convention for the inbound hook. They add no behavior over the base class;
they exist for platform-specific documentation and call-site clarity, not to
imply platform-specific certification.

## 12. Error model

Every error from `connector/http_client.py` is a typed subclass of
`SuperDocsConnectorError`, carrying `status_code`, `detail`, `retryable: bool`,
and (for `PayloadTooLargeError`) `suggested_action`:

| Class | HTTP status | Retryable |
|---|---|---|
| `ValidationError` | 400, 422 | No |
| `AuthenticationError` | 401 | No |
| `PermissionError` | 403 | No |
| `NotFoundError` | 404, expired/GC'd jobs | No |
| `ConflictError` | 409 (wrong `awaiting_kind`, concurrent revert) | No |
| `PayloadTooLargeError` | 413 | No — inspect `suggested_action` and switch strategy |
| `UnsupportedFormatError` | 415, or client-side `.doc`/unknown extension | No |
| `RateLimitError` | 429 | Yes — retried internally |
| `ServerError` | 500 | Yes — retried internally |
| `TimeoutError` | 504, network timeout, poll-loop timeout | Yes (504)/context-dependent |
| `UnknownSuperDocsError` | anything else | No, treated conservatively |

The `Authorization` header is never included in any error message or log
line (`connector/http_client.py` logs status/path only).

## 13. Retry model

Handled entirely inside `SuperDocsHTTPClient._request` / `_backoff` — every
operation gets this for free, no per-operation retry code:

- **429 with `Retry-After`**: honored exactly (the header value, not a
  computed backoff).
- **429 without `Retry-After`** (infrastructure-level, plain-text body):
  exponential backoff with jitter, same as 500.
- **500**: bounded exponential backoff (`min(2**(attempt-1), 30)` seconds),
  up to `ConnectorConfig.max_retries`.
- **504**: retried the same way at the HTTP layer, but the *right* fix is
  architectural — use `/v1/chat/async` instead of sync `/v1/chat` for
  anything that might run long, which this connector already does by default
  (§7).
- **400/401/403/404/410/415/422**: never retried — these are caller-side
  problems retrying won't fix.
- **413**: never blindly retried — `PayloadTooLargeError.detail` carries
  `suggested_action` from SuperDocs' response so the caller can switch
  strategy (e.g. the pre-signed upload path, §5).

Retry decisions are made on **status code and structured fields only** —
never on parsing human-readable error text.

## 14. Job lifecycle

```
pending -> in_progress -> completed
                        -> failed
                        -> cancelled
                        -> awaiting_approval -> [approve/continue] -> in_progress -> ... completed
```

Jobs are garbage-collected by SuperDocs roughly **one hour** after creation.
`poll_until_terminal`'s `max_poll_seconds` defaults to 55 minutes specifically
to raise a typed `TimeoutError` before that GC window, rather than polling a
job that no longer exists. **This connector does not persist job state to a
database** — `ConnectorJobState`-equivalent fields live only as long as the
background `asyncio.Task` does. If a recipe needs to survive a full connector
process restart mid-poll, the platform side should persist `job_id` +
`session_id` (both returned immediately, before any polling starts) and call
`poll_for_completion`/`submit_for_approval` again later — SuperDocs' own job
record is the source of truth up to the 1-hour GC window, not this connector.
This is a deliberate, documented trade-off, not an oversight (see §17).

## 15. Three recipes

See `recipes/` — each file's module docstring states its flow, retry
handling, failure branch, and callback usage explicitly. Summary:

1. **`recipe_1_generate_contract.py`** — template → async generate → returns
   immediately → background poll → callback. The simplest end-to-end flow.
2. **`recipe_2_edit_and_approve.py`** — two entry points
   (`start_edit_and_await_review`, `submit_review_and_resume`) because a real
   recipe can't hold a worker open waiting for a human to click "approve"
   possibly hours later. Demonstrates genuine item-level approve/reject
   (some changes approved, some rejected, in the same call).
3. **`recipe_3_approve_and_export.py`** — exports DOCX/PDF/Markdown
   independently; **one format failing does not abort the others** (see the
   module docstring for the explicit reasoning) — the recipe returns a
   per-format result so the platform decides what to do with a partial
   success, rather than the connector unilaterally discarding good artifacts.

All three are exercised end-to-end in `tests/test_recipes.py` against a fake
SuperDocs server, including the background-task poll+callback path actually
running to completion.

## 16. Configuration

Everything tunable lives in `ConnectorConfig` (`connector/config.py`) — no
hardcoded values anywhere else in the codebase:

```python
from connector import ConnectorConfig

config = ConnectorConfig(
    api_key=os.environ["SUPERDOCS_API_KEY"],   # required, validated
    base_url="https://api.superdocs.app",       # override for testing/proxying
    timeout_seconds=60.0,
    max_retries=4,
    poll_initial_interval_seconds=2.0,
    poll_max_interval_seconds=30.0,
    poll_backoff_factor=1.5,
    poll_jitter_ratio=0.2,
    max_poll_seconds=3300,
    callback_max_attempts=5,
    callback_initial_interval_seconds=1.0,
    callback_max_interval_seconds=60.0,
    callback_backoff_factor=2.0,
)
```

## 17. Testing

```bash
cd extensions/harishdtu/enterprise-integration-connector
pip install -e ".[dev]"
pytest -q
```

76 tests, 0 skipped, all mocking at the HTTP transport boundary via
`httpx.MockTransport` (injected through `SuperDocsHTTPClient(config,
transport=...)` and, for callback delivery, a fixture that monkeypatches
`connector.callbacks.httpx.AsyncClient` for the test's duration) — **no
`SUPERDOCS_API_KEY` is ever required to run the suite.** This exercises real
request serialization, response parsing, retry logic, and error mapping; only
the actual network call is faked.

See `docs/TASK2_VERIFICATION.md` for the full requirement-by-requirement
matrix and exact test counts per category.

## 18. Why no SSE

The brief explicitly prefers polling and calls out that implementing SSE
without a concrete requirement adds complexity for no benefit here — an
integration-platform recipe step is not well-suited to holding an `EventSource`
open anyway. **This connector implements REST polling only.**

This also means the well-known SuperDocs "double JSON parse" gotcha
(`JSON.parse(event.data)` then `JSON.parse(data.content)` for
`proposed_change_batch` and similar SSE events, per
`docs.superdocs.app/guides/human-in-the-loop`) **does not apply here** —
`GET /v1/jobs/{job_id}`'s `metadata.pending_changes` is already a structured
array of typed objects, confirmed directly against the SuperDocs OpenAPI
schema and the docs' own Python polling example. `connector/worker.py`'s
`_parse_poll_response` deserializes it once, with zero double-parsing. If SSE
is ever added later, it needs its own explicit test for the double-parse path
— none exists today because none is needed.

## 19. Limitations (stated honestly)

- **No native SuperDocs callback** — this connector's whole callback layer is
  necessarily self-built on top of polling; SuperDocs itself only offers
  pull-based mechanisms (§11).
- **`generate_from_template` is a composed abstraction**, not a real
  SuperDocs endpoint — verified explicitly, not invented (§6).
- **`X-Export-Warnings`' exact wire encoding is not fully documented** —
  the parser defends against two plausible encodings and preserves the raw
  header rather than silently dropping an unparseable warning (§10).
- **No connector-side job-state persistence** — background poll state lives
  only in the connector process's memory for the duration of the
  `asyncio.Task`; a full process restart mid-poll loses in-flight tracking
  (though not the underlying SuperDocs job itself, which the platform can
  still query by `job_id` up to the ~1-hour GC window) (§14).
- **Template resolution by `by_name`** depends on SuperDocs' own semantic
  template search, which this connector cannot verify deterministically
  picks the right template — prefer `template_id` when precision matters (§6).
- **Not certified with Workato, Tray, Boomi, or MuleSoft** — the callback
  layer is structured to adapt to each, but none of that adaptation has been
  run through an actual platform's certification process (stated at the top
  of this README and repeated here deliberately).
- **No Docker/deployment packaging** — this is a Python library/connector
  core, not a deployed service; wiring it into a specific platform's
  connector-hosting model (a Workato custom connector, a Tray custom
  service, etc.) is out of scope for this repository.
