# PROGRESS

## Phase 1-3 — scaffold and UI

- Created React + TypeScript Vite frontend scaffold.
- Created FastAPI backend scaffold.
- Added `.env.example` and local `.env` placeholders.
- Added Vercel and Render deployment configuration.
- Implemented Mastercard-inspired warm cream UI with a custom CloseOrbit logo.

## Phase 4 — audit remediation

An audit found the frontend and backend were two disconnected mockups with contradictory
fake data. The visual design was kept as-is; everything behind it was rebuilt.

### Data integrity

- Item ids are uuids and every route is scoped to one close. Decisions previously leaked
  across closes because seeded ids (`d1`, `c1`, `s3`) collided and handlers searched all closes.
- `create_close` builds from a template instead of cloning a fixture that arrived with two
  sign-offs already approved by people who had never seen the close.
- Readiness guards every ratio; a close with an empty section used to raise
  `ZeroDivisionError`.
- Sessions are signed tokens; the actor comes from the token, never the request body.
  Every handler used to hardcode `actor="Abhinay"`.
- A closed period is immutable.
- Persistence moved from a module-level dict to SQLite, so state survives restarts and is
  shared across workers.

### Features that now work

- Real multipart upload to disk, with download and sha256.
- Filename-based classification, confirmed explicitly through the mapping endpoint.
- Generation calls SuperDocs (mock or live) and builds the review queue from the response.
- Export assembles a downloadable zip of generated PDF sheets plus the source documents.
- The audit trail is exposed by `GET /closes/{id}/audit` and drives the timeline, which
  previously rendered five hardcoded strings.
- The close gate is enforced server-side.

### Wiring

- Added the frontend API client. There was previously no `fetch` call anywhere in `src/`.
- Dev port unified on 5180 across `vite.config.ts`, the npm script, and backend CORS.
- `FRONTEND_ORIGIN` documented; phantom Clerk/S3 settings removed.

### Tests

- 48 backend tests (endpoint, workflow, and a regression per audit finding).
- 11 frontend tests covering the readiness view model and formatting helpers.

## Phase 5 — the SuperDocs contract, end to end

Phase 4 made the app real but drove SuperDocs only during generation. Approval and export
were local state changes dressed up as document operations. Phase 5 put the whole contract
on the critical path.

### All four operations are now on the critical path

- `upload_document` and `send_edit_instruction` run during generation, as before.
- `approve_changes` now runs *before* an item is marked APPROVED. If SuperDocs fails the
  item stays PENDING with the error attached and the API returns
  `502 SUPERDOCS_APPROVAL_FAILED`, so a local success can never be faked.
  **Superseded in Phase 6** — the real API reviews a batch as a unit, so per-item
  approval was not merely slow but wrong.
- Rejection stays deliberately local-only — a rejected change is never sent, so it cannot
  reach the exported document. **Superseded in Phase 6** — rejections are now transmitted
  explicitly, which is the stronger guarantee.
- `export_document` now runs against the approved change set before the zip is assembled.
  A failure exports nothing and returns `502 SUPERDOCS_EXPORT_FAILED`.

### The operation ledger

- `services/superdocs_ops.py` records every adapter call — operation, mode, timestamp,
  duration, document and change ids, request id, success or failure with error text —
  against the close that caused it, in both modes.
- Exposed by `GET /closes/{id}/superdocs` and the SuperDocs tab, which also shows contract
  coverage across the four operations.
- Shipped inside every exported pack at `superdocs/operation-ledger.json`.
- Every stored response envelope passes through a redactor. A test asserts a configured
  API key appears in no API response, no database row, and no file in the exported zip.

### The Supporting Memo

- `services/memo.py` builds `Supporting Memo.pdf` from the uploaded source evidence: what
  was provided, what the checklist attests to, what SuperDocs proposed, how each proposal
  was decided, and who signed.
- Generated with the pack so it is visible immediately, and rebuilt at export so the
  packaged copy reflects decisions made after generation.

### Export integrity

- The app archive and the SuperDocs exported document are kept distinct: SuperDocs exports
  *a document*, the close pack is *an evidence bundle*, and the zip carries both.
- An export is invalidated whenever the close changes underneath it, so a pack can never
  be filed against evidence it does not contain.
- A generation abandoned by a crashed worker is released after `GENERATION_TIMEOUT_SECONDS`
  (default 900) instead of wedging the close forever.

### Tests

- 91 backend tests and 15 frontend tests, all passing; `npm run build` is clean.
- `test_superdocs_contract.py` (29 tests) covers approval calling SuperDocs, approval
  failure not producing false local success, export calling SuperDocs, memo generation and
  packaging, the ledger recording all four operations, mock determinism across two
  identical closes, and API-key non-leakage.
- `test_export_freshness.py` and `test_generation_recovery.py` cover export invalidation
  and abandoned-generation recovery.

### Left open at the end of Phase 5

- Live mode had never been executed against the real SuperDocs API. It was wired and
  type-correct, not verified. **Closed in Phase 6.**
- A live export returning a URL instead of inline bytes is recorded as a reference in
  `superdocs/export-metadata.json` but not fetched into the zip. **Still open.**
- Clerk, Postgres and object storage remained seams. **Closed in Phase 6.**

## Phase 6 — live integration against the real SuperDocs API

Phase 5 shipped live mode unverified. Running it exposed that the integration had been
written against a contract the API does not have.

### The endpoint was wrong

Source documents were being sent to `POST /v1/documents/upload`, which loads a file as
*the active editable document*. Uploading eight source files therefore replaced the
editor's document eight times — every response returned the same
`document_id: "doc_primary"`, which was visible from the first probe and not questioned.

Nothing survived as evidence, and the model said so directly:

> *"I couldn't detect any attached source documents in this session."*

Source files now go to `POST /v1/attachments/upload`, which is what makes a document
queryable while editing.

### Related corrections

- **Attachments index asynchronously.** The upload returns `status: "processing"` and a
  `job_id`; running the edit turn before indexing completes is indistinguishable from
  uploading nothing. Generation now waits on `GET /v1/attachments/status/{session_id}`.
  The first version of that gate read a key the payload does not contain, treated "no
  items" as "all finished", and returned instantly — reintroducing the race it existed to
  prevent.
- **The edit needs a document with sections to edit.** The working document was whichever
  source file uploaded first, normally the trial balance, while the instruction asked for
  revisions to a revenue summary and accrual exceptions. The model correctly proposed
  nothing. `generation.working_narrative()` now supplies a close-pack narrative as the edit
  target, with the source documents as attachments.
- **Approval is a batch.** The top-level `approved` field is the default for any change the
  request does not name, so approving one change decided the whole batch and completed the
  job. The second and later clicks failed with `400 Job is not awaiting approval`, and the
  first had already approved changes the reviewer went on to reject. Decisions are now
  recorded locally and submitted once, with rejections sent explicitly as `approved: false`.
- **The host was a placeholder.** `api.superdocs.com` does not resolve; the API is at
  `api.superdocs.app/v1`.
- **Timeouts are not retried.** Each attempt costs the full budget, so retrying a 300 s
  upload three times would push the job past the server's own generation deadline. Cheap
  transport faults still retry.
- **Errors are never blank.** Several `httpx` exceptions — `ReadTimeout` among them —
  stringify to the empty string, producing `SuperDocs request failed for POST …: ` and
  telling the operator nothing.

### The other three integrations are live

Neon Postgres, Storj object storage and Clerk were all verified end to end. Clerk exposed
one defect: `getToken()` serves a cached token that goes stale before it renews, producing
long alternating bursts of successes and `401`s. The client now retries a `401` once with
`skipCache`, and the server logs the real rejection reason instead of discarding it.

### Verified live

Eight attachment uploads, an HITL edit job returning five proposed changes drawn from the
actual source documents, a batch approval, and a PDF export.

## Phase 7 — product surface and performance

### The UI was built for a reviewer, not a controller

- The operation ledger was a primary tab showing snake_case RPC names, adapter mode,
  millisecond durations, document ids, request ids and raw exception text. It is now behind
  `?debug=1`.
- Raw identifiers, vendor vocabulary and lowercased database enums were removed from every
  user-facing surface. Error codes could previously render *as* the error text.
- The top navigation had five labels pointing at four workspace tabs, two of them the same,
  with no active state. They are now real destinations — Closes, Templates, Activity,
  Exports — built entirely from `GET /closes`, which already returns each close in full. No
  new endpoints were required.
- `readiness.canGenerate` was computed, threaded through the view model, and read by no
  component, so "Generate" was always enabled and the reason for failure arrived only
  afterwards. Every blocker is now a link to the tab that resolves it, every disabled
  control states why, and the workspace shows a numbered step track.
- A document whose filename matched no pattern had no suggested type and the only available
  button was guaranteed to fail. There is now a type picker.
- Added document deletion (`DELETE /closes/{id}/documents/{document_id}`) — record, bytes
  and audit entry — because one unprocessable file could otherwise block a close
  permanently.
- Sign-out and a user chip were added; the identity was already fetched and never rendered.

### Performance

Application CPU measured 0.0 ms. All latency was database round trips.

| Operation | Before | After |
| --- | --- | --- |
| `get_close` | 2,480 ms | 603 ms |
| `list_closes` | 2,533 ms | 603 ms |
| `mutate_close` | 3,453 ms | 2,098 ms |
| Round trips per decision | 5 | 2 |
| Close payload | 40,475 B | 23,693 B |

- **Connection pooling.** A fresh connection per query cost ~1,890 ms of handshake against
  a remote instance versus ~309 ms for the query — 86% of every call.
- **The ledger left the close payload.** 41% of every response, growing without bound, read
  by nothing but its own endpoint.
- **Redundant round trips removed** from the decision path.
- **`BEGIN` removed** from writes; psycopg opens the transaction with the first statement.
  Making the pool non-autocommit instead fixed writes but doubled read latency, and was
  reverted.

### Other fixes

- Generation polling used `setInterval` with an async callback, overlapping requests and
  retrying `401`s forever at 700 ms. It is now a chained `setTimeout` at 2 s that stops on
  auth failure, caps consecutive failures, and abandons a job that never settles.
- `saveBlob` revoked the object URL in the same tick as the click, cancelling every
  download before the browser read the blob.

### Tests

- 116 backend tests and 16 frontend tests.
- The three contract tests encoding per-item approval were rewritten for the batch model,
  and tests added for: no SuperDocs call until every change is decided, rejections
  transmitted as rejections, decisions surviving a failed submission, and document deletion
  removing record, bytes and export validity.

### Still open

- **No authorisation model.** Authentication is real; authorisation is absent.
- Writes remain ~2 s against a remote database — each close is one JSON document, so a
  mutation rewrites the whole thing.
- Indexing time scales with page count; a several-hundred-page PDF has taken 188 s.
- A live export returning a URL instead of inline bytes is still not fetched into the zip.
