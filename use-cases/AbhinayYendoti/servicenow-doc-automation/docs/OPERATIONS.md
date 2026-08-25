# Operations

Running it, configuring it, and diagnosing it when it misbehaves.

## Running

```bash
npm start          # build, then serve UI + API from one process on :8787
npm run server     # API only (expects dist/ to exist)
```

The server serves the built UI, the workflow API, and — in mock mode — the ServiceNow
instance, all from one port. It fails at boot on bad configuration, naming the variable:

```
Configuration is invalid:
  - SERVICENOW_ENABLED=true requires SERVICENOW_INSTANCE_URL.
```

`SIGINT`/`SIGTERM` flush run state synchronously before exit, so a deploy mid-review does
not strand a reviewer.

## Configuration

Everything is environment-driven. `.env.example` is the annotated source of truth.

### SuperDocs

| Variable | Default | Notes |
| --- | --- | --- |
| `SUPERDOCS_API_KEY` | — | Required unless replaying. Validated for an `sk_`/`lce_` prefix at boot. |
| `SUPERDOCS_BASE_URL` | `https://api.superdocs.app` | |
| `SUPERDOCS_REPLAY` | `off` | `off` \| `record` \| `replay`. See [Development](DEVELOPMENT.md#working-without-a-key). |
| `SUPERDOCS_CASSETTE_DIR` | `server/cassettes` | |

### ServiceNow

| Variable | Default | Notes |
| --- | --- | --- |
| `SERVICENOW_ENABLED` | `false` | `false` serves the mock instance in-process. |
| `SERVICENOW_INSTANCE_URL` | — | Required when enabled. |
| `SERVICENOW_USERNAME` / `SERVICENOW_PASSWORD` | — | Required when enabled. |
| `SERVICENOW_MOCK_USERNAME` | `svcflow.integration` | Credentials the mock accepts, so the auth path is exercised. |
| `SERVICENOW_MOCK_PASSWORD` | `mock-instance-secret` | |
| `SERVICENOW_MOCK_LATENCY_MS` | `60` | Raise to make loading states obvious; `0` for benchmarks. |
| `SERVICENOW_MOCK_FAILURE_RATE` | `0` | `0`–`1`. Injects `503`s to exercise error handling. |
| `SERVICENOW_WRITE_BACK` | `true` | Write the exported document back as a work note. |

### Server

| Variable | Default | Notes |
| --- | --- | --- |
| `PORT` | `8787` | |
| `LOG_LEVEL` | `info` | `debug` \| `info` \| `warn` \| `error`. |
| `NODE_ENV` | `development` | `production` switches logs to one JSON line per event. |
| `RUN_TTL_MS` | `3600000` | How long a document session stays resumable. |
| `RUN_LIMIT` | `200` | Bound on concurrent runs; oldest evicted past it. |
| `RUN_STATE_PATH` | `.runs` | **Directory.** One file per run. |

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/health` | Whether each system is answering, quota, live run count |
| `GET` | `/api/changes` | The reviewer's queue |
| `POST` | `/api/documents/upload` | Map a change and open a SuperDocs session |
| `POST` | `/api/documents/edit` | Start the edit |
| `GET` | `/api/documents/job/:jobId` | Run state (watchdog path) |
| `GET` | `/api/documents/stream` | Run state + activity over SSE (primary path) |
| `POST` | `/api/documents/decide` | One approve/reject |
| `POST` | `/api/documents/decide-batch` | Many, atomically |
| `POST` | `/api/documents/continue` | Resolve a large-edit pause |
| `POST` | `/api/documents/reedit` | Redo one section after a rejection |
| `POST` | `/api/documents/approve` | Reviewer sign-off |
| `POST` | `/api/documents/export` | Render, download, write back |
| `GET` | `/api/runs/:sessionId/audit` | The run's append-only history |

In mock mode, `/mock/servicenow/api/now/table/change_request` is a real Table API
(`GET` list, `GET` by sys_id, `PATCH`) plus `/api/now/stats/change_request`.

### Errors

Every failure has the same shape, so clients branch on `code`, not on message text:

```json
{ "error": { "code": "conflict", "message": "…", "detail": null,
             "retryable": false, "requestId": "req_efc43ea4" } }
```

`invalid_request` · `not_found` · `conflict` · `session_expired` · `quota_exhausted` ·
`rate_limited` · `upstream_failure` · `internal_error`

### Rate limits

Token bucket per IP per route. SuperDocs operations are billable; a retry loop in a browser
tab should not be able to spend the month.

| Route | Burst | Refill |
| --- | --- | --- |
| `upload`, `edit` | 6 | 0.2/s |
| `decide` | 30 | 2/s |
| `decide-batch`, `continue`, `approve` | 10 | 0.5/s |
| `reedit`, `export` | 10 | 0.2/s |

## Observability

**Logs.** One line per request with method, path, status, duration and a request id.
JSON in production, readable in development. Secrets are redacted by key
(`authorization`, `password`, `api_key`, `file_base64`, …) *and* by pattern — an `sk_…`
appearing anywhere in a logged value comes out as `sk_***`.

**Request ids.** Returned in `X-Request-Id` and embedded in every error envelope, so a
user-reported failure is greppable without guessing.

**Health.** `/api/health` is a product surface, not a diagnostics dump. It reports whether
ServiceNow and SuperDocs are answering, the remaining quota, and the live run count —
deliberately nothing about how either system is reached:

```json
{ "ok": true,
  "serviceNow": { "connected": true, "writeBack": true },
  "superDocs":  { "connected": true, "replaying": false, "quota": { "remaining": 486, ... } },
  "runs": 0 }
```

Both connections are genuinely probed — ServiceNow with a single-row query against the same
client the workflow uses — so a green status means the queue will actually load. Probes are
cached and primed at boot, so it answers in single-digit milliseconds and never generates
load proportional to page views.

**Topology lives in the boot log**, not the API. The endpoint is unauthenticated; base URLs
and instance addresses do not belong in it. `describeConfig` prints mode, instance URL and
SuperDocs base URL at startup.

## Quota

SuperDocs is metered per operation. `/api/agents/whoami` is polled (cached 60 s) and the
remaining count is shown in the UI header.

A run is refused up front when the account has nothing left — a run that dies halfway
through for quota is worse than one that never started. Roughly one operation per edit run;
`reedit` bills one more.

## Failure modes

| Symptom | Cause | Action |
| --- | --- | --- |
| Boot fails naming a variable | Invalid config | Fix the variable. It will not start half-configured. |
| `"SUPERDOCS_API_KEY is not set"` | No key, replay off | Set the key, or `SUPERDOCS_REPLAY=replay`. |
| `quota_exhausted` on upload | Monthly cap reached | Wait for reset, or upgrade the account. |
| Job sits at `awaiting_approval` with nothing to decide | A continue-prompt pause not being resolved | Should be automatic. If not, `POST /api/documents/continue`. |
| "Live progress dropped" notice | SSE connection lost | Cosmetic. The watchdog resumes polling within ~4 s. |
| `session_expired` (410) | Run exceeded `RUN_TTL_MS`, or was evicted | Start the run again. Raise `RUN_TTL_MS` if reviews are genuinely slower. |
| Approval refused with a verification failure | The document no longer matches ServiceNow | Working as intended. See [Verification](VERIFICATION.md). |
| Export succeeded, ServiceNow note missing | Write-back failed after export | Check logs for `servicenow_update_failed`. The document is safe — write-back is deliberately best-effort and runs after the bytes are in hand. |
| Replay says nothing was recorded | Cassette missing that interaction | Re-record: `SUPERDOCS_REPLAY=record`. |

## Limits

What this is not, and what each would take.

**No authentication or authorization.** Anyone who can reach the API can approve and
export. Reviewer identity is a typed name, not an authenticated principal — the audit trail
records who *said* they approved it. Real deployment needs SSO in front and the reviewer
taken from the session, not the request body.

**Single node.** Run state is local files. Two instances behind a load balancer would not
see each other's sessions. Shared state (Redis or Postgres) is the fix; the `RunStore`
interface is small enough to swap.

**Rate limiting is per process.** Effective limits multiply by instance count.

**The mock ServiceNow table is in-memory.** Write-backs are lost on restart. Fine for a
mock; irrelevant against a real tenant.

**No metrics or tracing export.** Structured logs only. No RED metrics, no spans.

**SSE has no resume.** A dropped stream re-reads full state rather than resuming from a
`Last-Event-ID`. Cheap here because state is small.

**Quota check can race.** The guard reads a value cached up to 60 s, so a run can start
against a stale non-zero count.

**The cassette is coarse.** ~2.9 MB, interleaving more than one recorded run. Replay
consumes responses per-key in recorded order, so a materially different flow can desync.

**Verification is literal.** See
[Verification § What the gate does not cover](VERIFICATION.md#what-the-gate-does-not-cover).
