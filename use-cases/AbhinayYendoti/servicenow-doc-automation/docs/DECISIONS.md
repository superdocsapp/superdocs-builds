# Decisions

The load-bearing calls, what was rejected, and — where there is one — the evidence that
settled it. Newest last.

Each entry is short on purpose. If a decision needs three paragraphs to justify, it is
usually two decisions.

---

## 1. SuperDocs is live. There is no hand-written mock.

**Context.** The task is to prove a document integration works. A mock of that integration
proves only that the app agrees with my reading of the docs.

**Decision.** Every document operation is a real HTTP call. If `SUPERDOCS_API_KEY` is
missing, the workflow refuses to start and says so.

**Rejected.** A "mock mode" that generates a plausible document locally. It would make the
demo more robust and the claim worthless — a fake document proves nothing about the
integration, and the failure it hides is exactly the one that matters.

**Consequence.** The app cannot run offline without a recorded cassette (§3), and a
SuperDocs outage is a visible outage rather than a silent downgrade. Both are correct.

---

## 2. ServiceNow is mocked as a real API, not as a fixture array.

**Context.** The task permits a fictional ServiceNow payload. The obvious implementation is
an array of objects handed straight to the app.

**Decision.** The mock is an HTTP surface — `/mock/servicenow/api/now/table/change_request`
— implementing basic auth, encoded queries, `sysparm_display_value`, `sysparm_fields`,
pagination headers, ServiceNow-shaped errors and PATCH write-back. One client
(`servicenow/client.js`) talks to it, and the same client talks to a real tenant.

**Rejected.** The fixture array. It would mean the code running in the demo is not the code
running against a real instance: no auth, no query parsing, no pagination, no display-value
resolution, no error handling, no latency.

**Evidence.** Serving `sysparm_display_value=all` faithfully — every field as
`{ value, display_value }`, dates in the caller's locale format — immediately exposed a bug
in the normalizer. It read `display_value` for datetimes, so `"08/18/2026 22:00:00"` failed
to parse and **every maintenance window silently became `null`**. Against a fixture array
that bug is invisible. Against a real tenant it is every record. It is now a test.

**Consequence.** Switching to a live instance is one environment variable. The mock cannot
quietly be more forgiving than the real thing, because it is the same code path.

---

## 3. Record/replay instead of a second mock.

**Context.** SuperDocs is metered. Iterating on the UI should not cost a month of
operations, and CI should not need a live key — but §1 rules out a hand-written fake.

**Decision.** `cassette.js` records real responses from a real run to disk, and replays
those exact bytes. Replay is opt-in, off by default, and reported in `/api/health` so the
UI can label a replayed run rather than passing it off as live.

**Consequence.** What replays is something the live API actually said. The recorded
cassette is ~2.9 MB and interleaves more than one run; see
[Operations § Limits](OPERATIONS.md#limits).

---

## 4. The human gate lives on the server.

**Context.** The reviewer's approval is the safety property. Anything a browser enforces,
a browser can skip.

**Decision.** Approving an edit that rewrites an owned value returns `409` regardless of
what the client asks. Export is refused until a reviewer has signed off *and* the finished
document still matches. Proposals are re-read from the server's own copy of what SuperDocs
sent, never from what the client echoes back.

**Consequence.** The UI disables the button as a courtesy. Deleting that code changes
nothing about what can actually happen.

---

## 5. Paraphrase is advisory, not blocking.

**Context.** Three verification rules catch three different failures. The third — added
prose that discusses a protected value without quoting it — is real but not fatal: the
canonical section still carries the verbatim value, so the document survives the final
gate.

**Decision.** Removal and mislabelled restatement of a preserved field block. Paraphrase
flags advisory and leaves the call to the reviewer.

**Rejected.** Blocking it. That would refuse a summary the reviewer probably wants, for a
document that still passes the export check.

See [Verification](VERIFICATION.md) for the rules and what each has caught.

---

## 6. The server decides what happens next.

**Context.** A guided UI can drift from the system it is guiding — the rail says one thing,
the enabled button says another.

**Decision.** `nextAction` is computed in `workflow.js` from real run state. The rail, the
highlighted button and the coaching copy all render that one value.

**Consequence.** There is exactly one next step by construction, and it is unit-testable
without a browser.

---

## 7. Run state is one file per run.

**Context.** State was a single JSON file, serialized and written synchronously on every
mutation. Runs carry document HTML.

**Decision.** One file per run, written asynchronously, only for runs that changed.

**Evidence.** With 100 open runs the old path blocked the event loop for ~10.5 ms per
persist, on a path that fires on every poll. Making the write asynchronous **barely
helped** — the cost was `JSON.stringify` of every run to save one, not the disk. Per-run
files cut it to ~1.3 ms and made it flat with the number of open reviews instead of linear.

**Consequence.** `RUN_STATE_PATH` is a directory. Session ids become filenames, so they are
validated at `create()` rather than trusted.

---

## 8. SSE is the signal; polling is a watchdog.

**Context.** The client polled every 4 s while the SSE connection was already pushing full
state on a 5 s floor. Every job was read from SuperDocs roughly twice, for identical
results.

**Decision.** While the stream is delivering, the poll stands down entirely. It fetches
only after the stream has been quiet longer than the server's own push interval, and
resumes immediately on a stream error.

**Evidence.** A live 22-second run: **one** job read, down from about eleven.

---

## 9. `compression` is a dependency rather than thirty lines.

**Context.** 209 KB of bundle was being served uncompressed. Writing a small gzip
middleware looked like the smaller change.

**Decision.** Use `compression`, Express's own middleware, with a filter that excludes
`text/event-stream`.

**Evidence.** The hand-rolled version deadlocked partway through a 188 KB file. `pipe`
waits for `drain` on the *response*, but under a naive wrapper it is the *compressor* that
fills up — so the response never drains and the transfer stops. That class of bug is
exactly what the maintained middleware exists to handle.

**Consequence.** One dependency. The event stream is verified uncompressed and still
arrives incrementally.

---

## 10. The reviewer's name is required by the UI, optional in the API.

**Context.** An approval with nobody's name on it is weak evidence, and the audit trail was
recording `reviewer: null`.

**Decision.** The sign-off UI requires a name and disables approval without one. The
endpoint still accepts an unattributed approval, because it has callers other than this
page.

**Consequence.** Attribution is a product guarantee, not a protocol one. Tightening the
endpoint is a one-line change if that becomes the right trade.

---

## 11. The mock instance is slow on purpose — but less so.

**Context.** The mock injects latency so the UI's loading states are exercised by something
real. The default was 180 ms on every ServiceNow call.

**Decision.** Default 60 ms. Enough to be real, little enough not to be felt. Raise
`SERVICENOW_MOCK_LATENCY_MS` to make loading states obvious, or set `0` for benchmarks.

---

## 12. The product surface says nothing about the implementation.

**Context.** The UI announced its own plumbing: "ServiceNow **mock** → SuperDocs live",
"11 closed changes · **mock instance**", "read from the **mock** ServiceNow instance".
`/api/health` published the mode, the instance URL and the environment name to every
browser tab.

**Decision.** The reviewer sees "ServiceNow, connected". `/api/health` reports whether each
system is answering and nothing about how it is reached. `/api/changes` no longer carries a
`source` field. Connectivity is genuinely probed rather than assumed, so a green dot means
the queue will load.

**Rejected.** Leaving the labels in. They leaked implementation detail into a product
surface, and a health endpoint that publishes internal topology to unauthenticated callers
is a bad habit regardless of what is behind it.

**Also rejected.** Inventing an instance hostname to make it look more real. Presenting the
integration honestly is the goal; fabricating a specific tenant is a different thing.

**Consequence.** Operators read topology from the boot log, which is not public. The
`replaying` flag stays in the payload deliberately — a recorded run must never be
presentable as a live one. And the docs still say plainly what backs it: hiding that from
engineers would cost the project the seam that makes it good.

**Evidence.** Zero occurrences of the implementation across `/api/health`, `/api/changes`,
`index.html` and the shipped JS bundle.
