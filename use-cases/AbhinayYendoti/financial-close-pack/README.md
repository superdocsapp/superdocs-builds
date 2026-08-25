# CloseOrbit — Financial Close Pack

A controller's workspace for assembling, reviewing, signing off and exporting a month-end
close pack, driven end to end by the SuperDocs document-operations API.

Every screen is backed by the API. Nothing is mocked in the UI, no state is invented in
the browser, and the close gate is enforced by the server.

---

## Contents

- [Stack](#stack)
- [Quick start](#quick-start)
- [How a close works](#how-a-close-works)
- [The SuperDocs integration](#the-superdocs-integration)
- [Live services](#live-services)
- [Performance](#performance)
- [Security](#security)
- [Testing](#testing)
- [Known limitations](#known-limitations)
- [Deployment](#deployment)

---

## Stack

| Layer | Choice |
| --- | --- |
| Frontend | React 19 + TypeScript + Vite |
| Backend | FastAPI (Python 3.10+) |
| Auth | Clerk when configured, otherwise a local demo session |
| Database | PostgreSQL (Neon) or SQLite, selected by configuration |
| Object storage | Any S3-compatible endpoint (Storj, R2, AWS), otherwise local disk |
| Documents | SuperDocs REST API (`api.superdocs.app/v1`) |

Each integration is selected by configuration and falls back to its local equivalent when
its variables are absent, so the app runs with no credentials at all and picks up real
services one at a time as they are supplied.

---

## Quick start

```bash
cp .env.example .env
npm --prefix frontend install
pip install -r backend/requirements.txt
```

Run the backend and the frontend in two terminals:

```bash
uvicorn backend.app.main:app --reload --port 8000
npm run dev
```

Frontend on `http://localhost:5180`, backend on `http://localhost:8000`.

On first boot the backend creates the schema and seeds one demo close (Acme India Pvt Ltd,
March 2026) whose source documents are generated PDFs.

> **Frontend env vars live in `frontend/.env`, not the repo root.** Vite reads env files
> from its own project root, so `VITE_API_BASE_URL` in the root `.env` is ignored and the
> client falls back to `http://localhost:8000`. `VITE_DEV_PORT` is read from the process
> environment by `vite.config.ts`, so setting it in any `.env` file has no effect either —
> pass it inline (`VITE_DEV_PORT=5190 npm run dev`) or edit the config. Whatever port you
> use must be in the backend's `FRONTEND_ORIGIN` or the browser will block every request.

### Running with no credentials at all

Leave `CLERK_SECRET_KEY`, `NEON_DATABASE_URL` and the `S3_*` variables blank and set
`SUPERDOCS_MODE=mock`. The app then runs entirely on SQLite, local disk, a local demo
session and the deterministic SuperDocs stand-in — no network access required.

---

## How a close works

The workspace is an ordered sequence, and the UI states which step you are on and what is
blocking the next one.

| # | Step | What happens |
| --- | --- | --- |
| 1 | **Collect documents** | Upload each required schedule; classify it so it counts toward the template's required types. |
| 2 | **Work the checklist** | Tick each control once its evidence exists. |
| 3 | **Build the pack** | Source documents go to SuperDocs as evidence; the AI drafts the close narrative and proposes changes. |
| 4 | **Review changes** | Approve or reject each proposed change. |
| 5 | **Collect sign-offs** | Each role approves in their own name. |
| 6 | **Export and close** | Produce the pack, then lock the period. |

Readiness is one number computed from six equally-weighted dimensions (documents,
checklist, generation, reviews, sign-offs, export). It is calculated **once, on the
server** — `frontend/src/lib/readiness.ts` only reshapes it for rendering, and deliberately
holds no second implementation.

Every blocker the gate reports is rendered as a link to the tab that resolves it, and every
disabled control states why it is disabled.

### The close gate

`POST /closes/{id}/close` succeeds only when all six dimensions are satisfied. A blocked
close returns `409 CLOSE_BLOCKED` with the blocker list and writes a `CLOSE_BLOCKED` audit
event. Once closed, the period is immutable: every mutating route returns `409`.

---

## The SuperDocs integration

The close pack drives four operations, in order, and records every call.

| Step | Contract operation | Live call |
| --- | --- | --- |
| 1 | `upload_document` | `POST /v1/attachments/upload` |
| 2 | `edit_document` | `POST /v1/chat/async` (`approval_mode: ask_every_time`), then job polling |
| 3 | `approve_changes` | `POST /v1/chat/{session_id}/approve` |
| 4 | `export_document` | `POST /v1/documents/export` |

Both modes go through the same `SuperDocsClientProtocol`, the same call sites and the same
ledger. Mock mode changes the transport, not the sequence.

### Three details that are easy to get wrong

**Source documents are attachments, not editor documents.** `POST /v1/documents/upload`
loads a file as *the active editable document* — uploading eight source files with it
simply replaces the editor's document eight times (every response returns the same
`document_id: "doc_primary"`). Nothing is retained as evidence and the model answers the
edit turn with *"I couldn't detect any attached source documents in this session."*
`POST /v1/attachments/upload` is what makes a file queryable while editing.

**Attachments index asynchronously.** The upload returns immediately with
`status: "processing"` and a `job_id`. Running the edit turn before indexing finishes is
indistinguishable from having uploaded nothing, so generation waits on
`GET /v1/attachments/status/{session_id}` until `processing_jobs` drains.

**Approval is a batch, not a series of clicks.** The top-level `approved` field is the
default for any change the request does not name, so a call carrying one change decides
*every* change in the batch and completes the job. Approving item by item therefore failed
the second and later clicks with `400 Job is not awaiting approval (status: completed)` —
and the first click had already silently approved changes the reviewer went on to reject.

The app records each decision locally and immediately, then submits the complete set in one
call when the last change is decided. **Rejections are transmitted explicitly as
`approved: false`**, which is a stronger guarantee than never sending them: the exported
document contains exactly what was approved and nothing else.

### Session and job identity

The API is session-centric while the app threads a single opaque `document_id`. Rather than
change every call site, the identifiers ride inside the strings the app already carries:

- `document_id` → `"<session_id>::<slug>"`
- `external_change_id` → `"<job_id>::<change_id>"`

### The operation ledger

`GET /closes/{id}/superdocs` returns contract coverage for all four operations plus an
append-only record of every call: operation, mode, timestamp, duration, document id, change
ids, request id, and success or failure with the error text. The same ledger ships in every
exported pack at `superdocs/operation-ledger.json`.

This is **engineering evidence, not a product surface**. It is not a tab — append
`?debug=1` to the URL to reach it. It is also deliberately excluded from the close payload
returned by `GET /closes` and `GET /closes/{id}`; see [Performance](#performance).

### Mock mode

`SUPERDOCS_MODE=mock` needs no API key and no network access. It is **not** a bypass: it
implements the same protocol, is invoked from the same call sites and produces the same
ledger entries. Everything it returns is deterministic — ids and receipts are derived by
hashing the inputs, so the same close always produces the same change set and
byte-identical exported documents. A test runs two identical closes and asserts the results
match exactly.

Its proposed changes and exported bytes are synthetic, and the exported PDF says so on its
first line.

### Live mode

```env
SUPERDOCS_MODE=live
SUPERDOCS_API_KEY=sk_your_key
SUPERDOCS_BASE_URL=https://api.superdocs.app/v1
```

Live mode has been **executed end to end against the real API**: eight attachment uploads,
an HITL edit job returning proposed changes drawn from the source documents, a batch
approval, and a PDF export.

Verify a key cheaply with `GET /v1/sessions` — it consumes no operations. Do not use
`/v1/users/*`, which accepts web-app session tokens only and returns `401` for a valid
`sk_` key.

### Two exports, kept apart

- **The SuperDocs exported document** — what `export_document` returned: the finished file
  produced from the approved changes. It ships in the zip under `superdocs/`.
- **The close-pack archive (zip)** — the file of record a controller retains. SuperDocs
  exports *a document*; a close pack is *an evidence bundle*, so the app builds it: the
  SuperDocs export plus the source documents, the Supporting Memo, the checklist, the
  review decisions, the sign-off sheet, the audit trail and the operation ledger.

An export is invalidated whenever the close changes underneath it, so a pack can never be
filed against evidence it does not contain.

---

## Live services

| Service | Enabled by | Fallback |
| --- | --- | --- |
| Clerk | `CLERK_SECRET_KEY` + a publishable key | Local demo session |
| PostgreSQL (Neon) | `NEON_DATABASE_URL`, or a `postgresql://` `DATABASE_URL` | SQLite file |
| S3-compatible storage | `S3_ENDPOINT_URL` + `S3_ACCESS_KEY_ID` + `S3_BUCKET_NAME` | `STORAGE_DIR` on disk |

**Clerk.** The frontend mounts behind `ClerkProvider` whenever `VITE_CLERK_PUBLISHABLE_KEY`
is present in `frontend/.env`. The backend verifies session JWTs against the instance JWKS
(RS256, issuer-checked); the JWKS URL and issuer are decoded from the publishable key, so
no extra variable is needed. Display name and role come from the Clerk Backend API, cached
per user, and are what sign-offs are attributed to.

With Clerk configured, `POST /auth/demo-session` returns `403` — an endpoint that issues a
session for a fixed identity with no credentials would otherwise be a complete
authentication bypass. `GET /auth/config` reports the active mode.

Clerk session tokens live about a minute and `getToken()` serves a cached copy that goes
stale before it renews. The API client therefore retries a `401` **once** with
`getToken({ skipCache: true })`, so expiry costs one extra round trip instead of surfacing
as an error. A second `401` with a freshly minted token is a genuine authentication failure
and is reported as one.

**PostgreSQL.** `store.py` speaks both dialects. Closes are stored as `jsonb` on Postgres
and text on SQLite; `mutate_close` holds `SELECT … FOR UPDATE` on Postgres and
`BEGIN IMMEDIATE` on SQLite, so read-modify-write is serialised either way.

**Object storage.** Two portability details are handled for non-AWS gateways: checksum
calculation is set to `when_required`, because boto3 ≥ 1.36 otherwise sends `aws-chunked`
bodies that Storj rejects with `MissingContentLength`; and prefix deletes issue one
`DeleteObject` per key, because the batch form requires a `Content-MD5` that Storj
enforces. The sha256 in every receipt is computed from the bytes written, never from a
provider ETag, which for multipart uploads is not a content hash.

**The test suite never touches any of them.** `conftest.py` blanks the Neon URL, the S3
settings and the Clerk key for every test, so the suite runs on a throwaway SQLite file and
local disk. This is a safety interlock, not tidiness: `reset_for_tests()` issues
`DELETE FROM closes`, so an unblanked environment would empty the production database.

---

## Performance

Measured against a remote Neon instance. Application CPU is **0.0 ms** — readiness and
serialisation are not the cost; getting to the database is.

| Operation | Before | After |
| --- | --- | --- |
| `get_close` (every screen) | 2,480 ms | **603 ms** |
| `list_closes` | 2,533 ms | **603 ms** |
| `mutate_close` (one decision) | 3,453 ms | **2,098 ms** |
| Round trips per review decision | 5 | **2** |
| Close payload | 40,475 B | **23,693 B** |

Four changes account for it:

1. **Connection pooling.** A fresh connection per query cost ~1,890 ms of TCP, TLS and auth
   handshake against a remote instance, while the query itself took ~309 ms — 86% of every
   database call was spent getting to the database. A process-wide pool (`min_size=1`, so
   the first request after an idle spell is also warm) removes it.
2. **The operation ledger is no longer sent on every read.** It was 41% of every close
   payload, grows without bound as a close is worked, and is read by nothing except
   `GET /closes/{id}/superdocs`, which loads the stored close directly.
3. **Redundant round trips removed.** A decision used to issue five sequential queries; the
   mutator already validates inside its own write transaction, so the pre-flight read
   proved nothing and the batch check now reuses the close the mutation returned.
4. **Writes carry no protocol overhead.** psycopg opens the transaction implicitly with the
   first statement, so a mutation is `SELECT … FOR UPDATE` + `UPDATE` + `COMMIT` rather
   than four round trips.

> Making the pool non-autocommit fixes writes but puts a `COMMIT` on every read, which
> measured **twice as slow**. The pool is autocommit; only writes wrap themselves in
> `connection.transaction()`.

The frontend contributes too: a routine mutation re-reads the close with **one** request
rather than the six `loadWorkspace` issues, because `GET /closes/{id}` already carries
documents, checklist, reviews, sign-offs, audit and readiness.

**What remains is geography.** A one-row, one-value query still takes ~295 ms — that is the
round-trip time to the Neon region and no amount of code removes it. Host the database near
your users, or run on SQLite locally where reads are sub-millisecond.

---

## Security

- **No credentials are recorded.** The SuperDocs API key never reaches the ledger, and
  every stored response envelope passes through a redactor that strips credential-shaped
  fields and bulk content. A test asserts a configured key appears in none of the API
  responses, the database, or any file in the exported zip.
- **The actor comes from the session token**, never from the request body. Sign-offs and
  review decisions are attributed to the authenticated user.
- **Clerk is the only accepted issuer when configured.** The local HMAC token is not a
  fallback, because that would leave the demo identity as a live bypass.
- **Auth failures are opaque to the client** (`invalid or expired`) and specific in the
  server log. An expiry race, a bad issuer and an unreachable JWKS endpoint are three very
  different problems, and telling them apart must not require giving a caller an oracle.
- **Uploads are capped** at 25 MB and filenames are sanitised before they reach storage.

There are **no role checks**: any authenticated principal can perform every mutation. See
[Known limitations](#known-limitations).

---

## Testing

```bash
npm test              # frontend + backend
npm run test:frontend
npm run test:backend
```

**116 backend tests and 16 frontend tests.**

| Suite | Covers |
| --- | --- |
| `test_superdocs_contract.py` | Batch approval, rejections transmitted explicitly, no call until every change is decided, export calling SuperDocs, memo generation and packaging, ledger completeness, mock determinism, API-key non-leakage |
| `test_workflow.py` | Upload → classify → generate → review → sign → export → close, plus document deletion |
| `test_live_integrations.py` | Backend selection and the interlocks: the suite can never be pointed at the configured production database or bucket, and a demo session cannot be minted while Clerk is live |
| `test_close_integrity.py` | Immutability once closed, cross-close isolation |
| `test_export_freshness.py` | Export invalidation when the close changes |
| `test_generation_recovery.py` | Abandoned-generation recovery |
| `test_readiness.py` | The six readiness dimensions and their blockers |

---

## Known limitations

Called out explicitly so nothing reads as more finished than it is.

- **No authorisation model.** Authentication is real; authorisation is absent. Any signed-in
  user can approve any change and close any period. This is the largest gap before real use.
- **Writes are ~2 s against a remote database.** Each close is one JSON document, so every
  mutation reads and rewrites the whole thing. Splitting reviews and audit into their own
  tables would fix it properly; that is a schema migration, not a tuning change.
- **Large documents are slow and variable to index.** A 484-page PDF took 2.4 s on one run
  and 188 s on another. Both are within budget, but a close containing several such files
  should move generation to a background worker.
- **A live export that returns a URL instead of inline bytes is not fetched.** The reference
  is recorded in `superdocs/export-metadata.json` and the zip ships metadata only for that
  file. Mock mode returns inline bytes, so the demo path is complete.
- **The final decision in a review batch is slower than the others**, because it carries the
  single SuperDocs submission for the whole batch.
- **`created_by` on the seeded close renders as a Python dict** in the exported close
  summary PDF, because the seed passes a plain dict where the API passes a `Principal`.
  Cosmetic, and confined to the seeded close.
- **The audit timeline is capped at the last 12 events** in the workspace. The full trail is
  on the Activity page and in the exported pack.
- **A generation abandoned by a crashed worker** is only released after
  `GENERATION_TIMEOUT_SECONDS` (default 900).
- **SQLite is single-writer.** Deployments on SQLite must run exactly one instance.

---

## Deployment

See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for Vercel and Render setup, required
environment variables, persistence, and the pre-production checklist.

For architecture and data-flow detail, see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
For diagnosing a failure, see [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md).

---

## Credit

The UI is warm and editorial, inspired by Mastercard's design language without using any
Mastercard brand assets. Demo data is fictional.
