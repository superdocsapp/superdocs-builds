# Development

Working on this without spending quota or breaking the guarantee.

## Setup

```bash
npm install
cp .env.example .env.local     # add SUPERDOCS_API_KEY
```

Two processes while iterating — Vite proxies `/api` to the server, so the UI hot-reloads
without restarting the backend:

```bash
npm run server                 # :8787  API + mock ServiceNow instance
npm run dev                    # :5173  UI
```

`npm start` builds and serves everything from `:8787`. Use it to check the production path
— compression, cache headers and the SPA fallback only exist there.

## Working without a key

Every edit run costs at least one billable SuperDocs operation, so UI work should not be
paid for in quota. Record a real run once, then replay it:

```bash
SUPERDOCS_REPLAY=record        # in .env.local — run the flow once against the live API
SUPERDOCS_REPLAY=replay        # now serve those exact recorded responses
```

Replay needs no API key at all, which is also how this runs in CI.

What replays is bytes a real run produced — there is no hand-written SuperDocs mock
anywhere in the tree, deliberately ([Decisions §1](DECISIONS.md)). The UI labels a replayed
run rather than passing it off as live.

Replay serves responses per key in recorded order. A materially different flow will run
past the end of what was recorded and fail with a clear message; re-record when the
workflow changes shape.

## Tests

```bash
npm test           # 80 tests
npm run typecheck
```

| Suite | What it actually exercises |
| --- | --- |
| `servicenow/source.test.js` | Boots the mock Table API on an ephemeral port and drives the real client at it over HTTP — auth, encoded queries, ordering, projection, write-back. |
| `documentMapping.test.js` | The verification rules, including the exact strings the live API produced. |
| `workflow.test.js` | State derivation and `nextAction`. |
| `runStore.test.js` | Persistence: per-run files, restore, eviction, corrupt files, shutdown. |
| `cache.test.js` | Coalescing and stale-while-revalidate, with an injected clock. |

**The bar for a test here:** exercise the seam, not a mock of it. The ServiceNow suite runs
real HTTP because that is what caught the datetime-parsing bug a fixture array would have
hidden ([Decisions §2](DECISIONS.md)).

**When you touch verification,** add the case to `documentMapping.test.js` first. If a live
run produces a new failure, paste the model's actual output into the test rather than a
paraphrase of it — three of the existing cases are verbatim captures, and they are the
valuable ones.

## Conventions

**Where things go.** `workflow.js` is pure and has no I/O. `superdocs.js` is the only
module that calls SuperDocs. `servicenow/client.js` is the only module that speaks the
Table API. `domain.ts` holds types and formatting — no data, no document logic. If you find
yourself importing `superdocs.js` into a second place, that is the signal to reconsider.

**Errors.** Throw from `errors.js`; the error middleware turns anything into the standard
envelope and translates upstream failures on the way out. Do not hand-roll a response
shape.

**Comments explain why.** The code says what it does. Comments carry the reason it is not
the obvious thing — a bug it prevents, an API behaviour it works around, a trade-off taken.
Several comments in this tree are the only record of a live-API behaviour that cost an
afternoon to find; keep that standard.

**Client state.** The server owns run state and `nextAction`. If the browser is computing
something about what the reviewer should do next, that logic belongs in `workflow.js`.

## Performance baseline

Measured, not assumed. Re-measure before claiming a regression.

| | Value |
| --- | --- |
| `GET /api/health` | ~5 ms (primed at boot, stale-while-revalidate) |
| JS bundle on the wire | 58.8 KB gzipped (187.8 KB raw) |
| `/api/changes` payload | ~2.0 KB gzipped (6.1 KB raw) |
| Job reads during a 22 s run | 1 |
| Persist cost, 100 open runs | ~1.3 ms, flat |
| `describeJob` on a real payload | ~0.21 ms |
| `verifyProposedChange` | ~0.11 ms |

The profiling pass that produced these started by benchmarking the verification gate and
job normalization — the obvious suspects — and found them costing fractions of a
millisecond. They were left alone. Every real win was in I/O, redundancy, or transfer
([Decisions §7–9](DECISIONS.md)).

If you are optimizing, measure first. The cheapest way in is a script under the scratch
directory importing the module directly and timing it against a payload pulled from the
cassette — real shapes, not synthetic ones.

## Gotchas

**`RUN_STATE_PATH` is a directory,** not a file. It was a file before
([Decisions §7](DECISIONS.md)).

**The mock instance holds state in memory.** Write-backs from a previous run disappear on
restart, and the queue reorders after one because `sys_updated_on` moves.

**`CHG0010054` is incomplete on purpose.** It exercises the validation gate. The UI opens
on the first *valid* change so the first click is never a dead end.

**Do not compress the event stream.** `httpCache.js` excludes `text/event-stream`
explicitly. A buffered event stream stops being one, and the symptom is a feed that arrives
in silent bursts.

**SSE headers use `setHeader`, not `writeHead`.** Headers passed to `writeHead` are not
readable via `getHeader`, and the compression filter has to see the content type to skip
the stream.

**Two kinds of pause look identical.** `status: "awaiting_approval"` means either a change
batch or a large-edit continue prompt, told apart only by `metadata.awaiting_kind`. Treat
the second as the first and the job waits forever. There is a test.
