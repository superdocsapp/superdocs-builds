# Architecture

How the pieces fit, and why they are shaped the way they are.

---

## Shape

```
Browser ──► FastAPI ──► Postgres (Neon) or SQLite      state
                    ├─► S3-compatible or local disk    bytes
                    └─► SuperDocs REST API             document operations
```

One FastAPI router (`backend/app/api/routes.py`), one storage abstraction, one document
adapter behind a protocol. There is no service mesh and no queue; generation runs as a
FastAPI background task.

## Layout

| Path | Responsibility |
| --- | --- |
| `backend/app/api/routes.py` | Every HTTP route. Auth, validation, transaction boundaries. |
| `backend/app/core/config.py` | Settings and the derived predicates (`is_postgres`, `s3_enabled`, `clerk_enabled`). |
| `backend/app/core/security.py` | Session issuing, Clerk JWT verification, the `Principal`. |
| `backend/app/db/store.py` | Connection pool, transactions, both SQL dialects. |
| `backend/app/services/closes.py` | The close document: construction, mutation helpers, audit, serialisation. |
| `backend/app/services/readiness.py` | The six-dimension gate. The single source of truth. |
| `backend/app/services/generation.py` | The generation job and the close narrative it drafts. |
| `backend/app/services/superdocs_ops.py` | The operation ledger and its redactor. |
| `backend/app/services/export.py` | Zip assembly. |
| `backend/app/services/memo.py` | The Supporting Memo artifact. |
| `backend/app/integrations/superdocs/client.py` | The protocol, the live REST client, the deterministic mock. |
| `frontend/src/App.tsx` | The workspace shell and every tab. |
| `frontend/src/pages.tsx` | The top-nav destinations (Closes, Templates, Activity, Exports). |
| `frontend/src/lib/guidance.ts` | Blockers → the tab that resolves them; step state; next action. |
| `frontend/src/lib/api.ts` | The API client, error translation, token refresh. |

---

## Data model

A close is **one JSON document**, stored as `jsonb` on Postgres and text on SQLite:

```
close
├── entity, period, owner, due_date, template_id
├── closed_at, closed_by          immutability marker
├── generating, generating_since  generation lock
├── documents[]                   uploads + classification + storage_key
├── checklist[]                   controls and their evidence
├── reviews[]                     proposed changes and decisions
├── signoffs[]                    roles and approvals
├── audit[]                       append-only, attributed
├── superdocs_operations[]        append-only ledger (never sent to the client)
├── superdocs_export              the finished document's metadata
└── export                        the archive record
```

**Why one document.** Every read a screen performs is one row, and a mutation is naturally
atomic without cross-table locking. The cost is that a write rewrites the whole document —
which is the dominant remaining latency (see the README's *Performance* section). Splitting
`reviews` and `audit` into their own tables is the correct next change if writes matter more
than read simplicity.

**Concurrency.** `mutate_close` is read-modify-write inside one transaction:
`SELECT … FOR UPDATE` on Postgres, `BEGIN IMMEDIATE` on SQLite. Both prevent two writers
reading the same close and each clobbering the other.

---

## Readiness is computed once

Six equally-weighted dimensions, averaged:

1. required document types present (a type counts only when some document is `READY` **and**
   carries that type)
2. checklist complete
3. pack generated
4. every review resolved
5. every sign-off approved
6. exported

Two gates fall out of it:

- `ready_for_generation` — documents and checklist complete. Enforced at
  `POST /closes/{id}/generate` (`409 GENERATION_BLOCKED`).
- `ready_for_close` — no blockers at all. Enforced at `POST /closes/{id}/close`
  (`409 CLOSE_BLOCKED`).

`blockers` is a list of plain-English strings. There is no separate copy layer: the server's
wording is what the user reads, and `frontend/src/lib/guidance.ts` maps each string to the
tab that resolves it.

> The frontend once held a second, independent readiness calculation. It drifted from the
> server's — different denominators, different blockers — and was the only thing the close
> button consulted. `frontend/src/lib/readiness.ts` is now a reshaper and nothing else.

---

## The SuperDocs adapter

```python
class SuperDocsClientProtocol(Protocol):
    async def upload_document(filename, content) -> dict
    async def edit_document(document_id, instruction, document_html=None) -> list[dict]
    async def approve_changes(document_id, change_ids, rejected_change_ids=None) -> dict
    async def export_document(document_id, approved_change_ids=None) -> dict
```

`get_client()` returns the live client or the deterministic mock based on
`SUPERDOCS_MODE`. Both are driven from the same call sites and produce the same ledger
entries.

### Impedance mismatches, and how they are resolved

| SuperDocs | The app | Resolution |
| --- | --- | --- |
| Session-centric | Threads one opaque `document_id` | Session id rides inside the id: `"<session_id>::<slug>"` |
| Approval needs a `job_id` | Only knows change ids | Job id rides inside the change id: `"<job_id>::<change_id>"` |
| Reviews a batch as a unit | Decides item by item | Decisions recorded locally; the batch submitted once, when the last one is made |
| Attachments index asynchronously | Expects upload to mean ready | Generation polls `/attachments/status` until it drains |
| An editable document is required to edit | Only has source PDFs | `generation.working_narrative()` supplies a close-pack narrative as the edit target |

### The working document

Source documents are **evidence** (attachments). The thing being **edited** is a close-pack
narrative with named sections — revenue summary, accrual exceptions, checklist footnotes,
balance-sheet movements, management commentary — built by
`generation.working_narrative()`.

This matters: the working document was once whichever source file uploaded first, normally
the trial balance. The instruction asks for revisions to sections a trial balance does not
contain, so the model correctly proposed nothing and generation failed with *"proposed no
changes"*.

### The ledger

`superdocs_ops.call()` wraps every adapter invocation and records operation, mode,
timestamp, duration, document and change ids, request id, and outcome. Failures are
recorded as thoroughly as successes — a call that failed and a call that never happened
must not look the same.

`superdocs_ops.redact()` strips credential-shaped fields and bulk content from every stored
envelope before it is persisted.

---

## Request lifecycle: approving a change

1. `POST /closes/{id}/reviews/{rid}/approve`
2. `_decide()` opens one write transaction: `ensure_mutable`, `_require_generated`,
   `find_review`, update status, write the audit entry, invalidate any export.
3. `_submit_batch_if_complete()` inspects the close the mutation returned. If any review is
   still `PENDING`, it stops — a partly decided batch must never be submitted, because the
   undecided remainder would be resolved by default.
4. When the last decision lands, one `approve_changes` call carries every decision,
   approvals and rejections alike. The receipt is attached to the approved items.
5. If that call fails, the reviewer's decisions stand and the failure is logged; the export
   retries the submission rather than shipping an unconfirmed batch.

Two round trips in the common case, three when the batch is submitted.

---

## Storage

`services/storage.py` presents `put_stream`, `put_bytes`, `get_bytes`, `exists`,
`delete_key` and `delete_prefix`, and picks S3 or local disk from configuration. Callers
never learn which is active.

Documents are keyed `closes/{close_id}/documents/{document_id}/{filename}`, so deleting a
close is a prefix delete.

**Ordering matters on delete:** the record is committed first, then the bytes. A failed
byte-delete leaves an unreferenced object, which the prefix delete reaps with the close. The
reverse order would leave a document that lists in the UI and 404s on download.

---

## Frontend

No router. One `App.tsx` holds two axes of state: `view` (the top-nav destination) and
`activeTab` (the step inside the workspace).

The top-nav destinations are built entirely from `GET /api/v1/closes`, which returns each
close in full — including its audit trail and export record — so Closes, Activity and
Exports are client-side aggregations needing no extra endpoints.

**Generation polling** uses a chained `setTimeout`, not `setInterval`: an interval with an
async callback overlaps requests whenever a response outlives the period. It stops on an
auth failure, caps consecutive failures, and abandons a job that never settles.

---

## Deliberate omissions

- **No queue.** Generation is a FastAPI background task. A crashed worker is recovered by
  `GENERATION_TIMEOUT_SECONDS`, not by redelivery.
- **No migrations.** `init_db()` issues `CREATE TABLE IF NOT EXISTS`. The schema is two
  tables; a real migration tool is warranted the moment the JSON document is decomposed.
- **No cache.** Every read hits the database. At this size the round trip dominates and a
  cache would add staleness for little gain.
- **No authorisation.** Deliberate for the current stage, and the first thing to add.
