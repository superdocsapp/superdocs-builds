# Architecture

How the system is put together, where the seams are, and where to change things.

For *why* it is built this way, see [Decisions](DECISIONS.md).

## Shape

```
Browser
  │  fetch + EventSource
  ▼
Express server ──────────────────────────────────────────────┐
  │                                                          │
  │  HTTP (basic auth, sysparm_*)      HTTPS (Bearer)        │
  ▼                                    ▼                     │
Mock ServiceNow instance          SuperDocs API              │
(same process, real Table API)    (live, api.superdocs.app)  │
  ▲                                                          │
  └──────────── PATCH work note after export ────────────────┘
```

The browser never talks to SuperDocs. The API key is server-side and stays there.

## Request path

```
ServiceNow row
  → ServiceNowClient        one HTTP client; mock and live differ only by base URL
  → normalizeChangeRow      the one place field names are translated
  → ChangeRequest           canonical shape; nothing downstream sees a ServiceNow row
  → mapChangeToSections     values copied verbatim, never reworded locally
  → SuperDocs upload/edit   the model does the writing
  → describeJob             job → UI state, verifying every proposal on the way
  → verification gate       blocked / advisory / safe
  → reviewer sign-off       attributed, re-verified server-side
  → export + write-back
```

## Modules

### Server

| File | Responsibility |
| --- | --- |
| `index.js` | Routes, middleware, boot. The only place the pieces are wired together. |
| `config.js` | Environment → validated config. Fails at boot, by variable name. |
| `workflow.js` | Pure. SuperDocs job → UI state, and the single `nextAction`. |
| `documentMapping.js` | Mapping, validation, and the verification rules. |
| `superdocs.js` | The only place that calls SuperDocs. |
| `cassette.js` | Record/replay transport sitting under `superdocs.js`. |
| `runStore.js` | Run state: TTL, bounded, restart-safe, audit trail. |
| `cache.js` | `singleFlight` and `staleWhileRevalidate`. |
| `httpCache.js` | gzip and asset cache headers. |
| `errors.js` | One error envelope for every failure. |
| `log.js` | Structured logs, request ids, secret redaction. |
| `servicenow/mockApi.js` | The mock instance, as a real Table API. |
| `servicenow/client.js` | The one Table API client. |
| `servicenow/source.js` | Adapter → canonical `ChangeRequest`. |
| `servicenow/fixtures.js` | Stored rows, in ServiceNow's own shape. |

### Client

| File | Responsibility |
| --- | --- |
| `App.tsx` | Orchestration and run state. No document logic. |
| `api.ts` | Client for this app's server, including the SSE subscription. |
| `domain.ts` | Shared types and formatting. No data, no document logic. |
| `components/` | Rail, next action, agent feed, verification console, proposal card, audit trail, sign-off, guided tour. |

## The four seams

Everything that makes this changeable — or deliberately opaque — lives at four boundaries.

**1. `ServiceNowClient` — mock vs. live.** One HTTP client. `config.serviceNow.mode`
decides which base URL and credential it gets. Nothing downstream can tell which answered,
because both speak the same Table API over the same transport. Switching is one env var.

**2. `ChangeRequest` — the canonical record.** `normalizeChangeRow` is the only function
that knows ServiceNow field names. Document mapping, verification and the UI consume the
canonical shape. A ServiceNow schema change stops at that function.

**3. `/api/health` — status, not topology.** The browser learns whether ServiceNow and
SuperDocs are answering. It does not learn how either is reached, because that is an
operational fact and the endpoint is unauthenticated. Operators read topology from the boot
log instead.

**4. `nextAction` — the server owns what happens next.** Computed in `workflow.js` from
real run state. The rail, the highlighted button and the coaching copy all render that one
value, so the UI cannot suggest two different next steps at once.

## Run state

A run is the server-side record of one document session: the ServiceNow change it maps to,
the proposals SuperDocs sent, the decisions taken, the approval, and an append-only audit
trail.

The browser holds a session id and nothing else that matters. Verification and export
re-read the proposal from the server's own copy, so a client cannot get an edit approved by
sending back a friendlier version of it.

Runs expire (TTL), the store is bounded (oldest evicted), and each run persists to its own
file under `RUN_STATE_PATH` so a restart mid-review does not strand a reviewer holding a
session id the server has never heard of.

## Live updates

Two channels, one of them primary:

- **SSE (`GET /api/documents/stream`)** — the server proxies SuperDocs' own progress
  events as `activity`, and pushes fully-derived run state as `state` whenever something
  structural happens, plus a 5s floor.
- **Polling (`GET /api/documents/job/:jobId`)** — a watchdog. While the stream is
  delivering it stands down entirely; it only fetches once the stream has been quiet longer
  than the server's push interval.

The client never merges partial updates. Every `state` event is the whole picture.

## Where to change things

| Change | Touch |
| --- | --- |
| Point at a real ServiceNow tenant | `.env.local` only |
| Add a field to the document | `FIELD_MAPPING` in `documentMapping.js` |
| Protect another ServiceNow value | `PRESERVED_FIELDS` / `ADVISORY_FIELDS` |
| Change what the reviewer is told to do next | `nextAction` in `workflow.js` |
| Add a SuperDocs endpoint | `superdocs.js`, and only there |
| Change the ServiceNow query | `ServiceNowSource.listChanges` |

## Testing strategy

Tests run against real seams rather than mocks of them.

| Suite | Covers |
| --- | --- |
| `servicenow/source.test.js` | The mock Table API over **real HTTP** — auth, encoded queries, ordering, projection, write-back — plus normalization. |
| `documentMapping.test.js` | The verification rules, including the exact mutations the live API produced. |
| `workflow.test.js` | State derivation and `nextAction`, including the continue-prompt pause. |
| `runStore.test.js` | Persistence: per-run files, restore, eviction, corruption, shutdown. |
| `cache.test.js` | Single-flight coalescing and stale-while-revalidate. |

80 tests. No test mocks SuperDocs by hand; what is replayed was recorded from a real run.
