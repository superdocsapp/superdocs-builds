# Troubleshooting

Failure modes this system has actually produced, what each one looks like, and the fix.

---

## Where to look first

| Symptom | Look at |
| --- | --- |
| A request failed | The backend log — errors are logged with cause, and shown to the user in plain language |
| A SuperDocs call failed | `GET /closes/{id}/superdocs`, or `?debug=1` in the UI |
| A close will not close | The blocker list on the Overview tab; each one links to its tab |
| Something is slow | The *Performance* section of the README — it is almost always database round trips |

The operation ledger records failures as thoroughly as successes. A call that failed and a
call that never happened must not look alike.

---

## Authentication

### Repeated `401` on the same endpoint, in bursts

**Looks like:** dozens of `401`s in the console, interleaved with successes, cycling on
roughly a one-minute period.

**Cause:** Clerk session tokens live about a minute, and `getToken()` serves a cached copy
that goes stale before it renews. A sustained window of requests replays a token the server
has already rejected.

**Fix:** already handled — `lib/api.ts` retries a `401` once with
`getToken({ skipCache: true })`. If you still see bursts, confirm the browser is running
current code (hard-reload; a stale tab keeps the old client).

### Every request `401`s, with no successes

Check `GET /api/v1/auth/config`:

- `{"mode": "clerk"}` — sign in through Clerk. `POST /auth/demo-session` returns `403` by
  design while Clerk is configured.
- `{"mode": "demo"}` — the demo session should work. If it does not, `SESSION_SECRET`
  probably changed, which invalidates every issued token.

The server log names the real reason (`Clerk token rejected: <type>: <detail>`). An expiry
race, a bad issuer and an unreachable JWKS endpoint are very different problems; the client
is told only "invalid or expired" so it cannot be used as an oracle.

### A poll loop that never stops

A polling loop must treat an auth failure as terminal and cap consecutive failures.
`setInterval` with an async callback also overlaps requests whenever a response outlives
the period — use a chained `setTimeout`, as the generation poller does.

---

## Generation

### `finished with status 'completed' and proposed no changes`

**Cause, most likely:** the model could not see the source documents. It reports this
directly in the job's `intermediate_responses`:

> *"I couldn't detect any attached source documents in this session."*

Source files must go to `POST /v1/attachments/upload`. `POST /v1/documents/upload` loads a
file as *the active editable document*, so uploading several source files just replaces the
editor's document repeatedly — every response returns the same `document_id: "doc_primary"`,
which is the tell.

**Cause, also possible:** the working document has no sections matching the instruction.
The edit target must be a close narrative with named sections, not a source schedule; a
trial balance contains no "revenue summary" to revise. See
`generation.working_narrative()`.

**Diagnosing:** fetch the job and read the trace.

```bash
curl https://api.superdocs.app/v1/jobs/JOB_ID -H "Authorization: Bearer $SUPERDOCS_API_KEY"
```

`metadata.intermediate_responses` usually says plainly what the model did or could not do.

### `ReadTimeout: the request timed out before SuperDocs responded`

Indexing time scales with the document's **page count**, not its byte size. A 484-page,
2.7 MB PDF has taken anywhere from 2.4 s to 188 s.

- Under `UPLOAD_TIMEOUT` (300 s): it succeeds, slowly.
- Over it: generation fails and names the file.

Timeouts are deliberately **not** retried. Each attempt costs the full timeout budget, so
three retries of a 300 s upload would block generation for fifteen minutes and push the job
past the server's own generation deadline. Cheap transport faults — a mid-flight
disconnect — are retried three times.

If a close routinely contains several very large documents, move generation to a background
worker rather than raising the timeout again.

### Generation is stuck

`generating` is released after `GENERATION_TIMEOUT_SECONDS` (default 900). Check state:

```sql
SELECT data->>'generating', data->>'generating_since' FROM closes WHERE id = '<close_id>';
```

### An empty SuperDocs error message

Several `httpx` exceptions — `ReadTimeout` chief among them — stringify to the empty
string, producing a useless `SuperDocs request failed for POST …: `. `_describe()` in the
client guarantees a non-empty description. If you see a blank error, the client is out of
date.

---

## Review

### `400 Job is not awaiting approval (status: completed)`

**Cause:** the batch was already decided. SuperDocs reviews a batch as a unit — the
top-level `approved` field is the default for any change the request does not name — so a
call carrying one change decides *every* change and completes the job.

**Fix:** already handled — decisions are recorded locally and the complete set is submitted
in one call when the last change is decided. If you see this, something is submitting per
click again.

This mattered for correctness, not just for errors: per-click approval silently approved
changes the reviewer went on to reject.

### Approving feels slow

The final decision in a batch carries the single SuperDocs submission, so it is slower than
the others. Every earlier click is local and immediate.

If *all* decisions are slow, the cause is database latency rather than SuperDocs — see
[Performance](#performance) below.

---

## Export and download

### "Download pack" does nothing

**Cause, most likely:** the object URL was revoked in the same tick as the click, which
cancels the download before the browser reads the blob. `saveBlob()` keeps the URL alive
for 60 s — there is no completion event for an anchor download, so a timeout is the only
reliable signal.

**Cause, also possible:** there is nothing to download. `GET /closes/{id}/export/download`
returns `409 NOT_EXPORTED` until the pack is built. Confirm server-side:

```sql
SELECT data->>'exported', data->'export'->>'size' FROM closes WHERE id = '<close_id>';
```

### The export keeps invalidating

By design. Any change to the close clears `exported` and writes an `EXPORT_INVALIDATED`
audit event, so a pack can never be filed against evidence it does not contain. Export
last, after every decision and sign-off.

---

## Performance

### Everything is slow

Application CPU is effectively zero; latency is the database round trip. Measure the split:

```python
import time, psycopg
t = time.perf_counter(); conn = psycopg.connect(URL); print("connect", time.perf_counter() - t)
t = time.perf_counter(); conn.execute("SELECT 1").fetchone(); print("query", time.perf_counter() - t)
```

- **connect ≫ query** — pooling is not active. `psycopg-pool` must be installed and
  `store._postgres_pool()` in use.
- **connect ≈ 0, query ~300 ms** — that is geography. Host the database near your users, or
  develop against SQLite.

A one-row, one-value query is the floor: if `close_exists` takes 295 ms, no query will beat
it.

### Writes are much slower than reads

Expected. Each close is one JSON document, so a mutation reads and rewrites the whole thing
inside a transaction. Splitting `reviews` and `audit` into their own tables is the real fix.

Do **not** make the pool non-autocommit to speed up writes: it adds a `COMMIT` to every
read and measured twice as slow overall. Writes wrap themselves in
`connection.transaction()` instead.

---

## Local environment

### `[Errno 10048] only one usage of each socket address`

Port 8000 is already held, usually by an earlier backend. On Windows, `pkill` under Git
Bash does not match it:

```powershell
Get-NetTCPConnection -LocalPort 8000 -State Listen |
  Select-Object -ExpandProperty OwningProcess -Unique |
  ForEach-Object { Stop-Process -Id $_ -Force }
```

A health check can return `200` from the *old* process while the new one has already died
on bind — confirm the PID and its start time, not just the status code.

### Every browser request fails before reaching a route

CORS. `FRONTEND_ORIGIN` must match the frontend's origin exactly, scheme included. Use
`ADDITIONAL_CORS_ORIGINS` (comma separated) for preview domains.

### Frontend env vars have no effect

Vite reads env files from `frontend/`, not the repo root. `VITE_DEV_PORT` is read from the
process environment by `vite.config.ts`, so no `.env` file sets it — pass it inline.

---

## Data

### Removing a document

`DELETE /api/v1/closes/{id}/documents/{document_id}` removes the record and the stored
bytes, writes a `DOCUMENT_DELETED` audit event, and invalidates any export. Refused with
`409` once the period is closed. The UI has a per-row control with confirmation.

This exists because one unprocessable file could otherwise block a close permanently, with
no way out but editing the database by hand.

### Resetting to a clean state

Deleting `var/` restores the seeded demo close on next boot — **only on SQLite**. On Neon
the state is remote and `var/` is irrelevant.

Never point the test suite at a real database: `reset_for_tests()` issues
`DELETE FROM closes`. `conftest.py` blanks the Neon URL, S3 settings and Clerk key for
exactly this reason.
