# Progress & assumptions log

Per the brief: a logged assumption is fine, an unstated one is not. This file
records decisions made while building, so they can be confirmed or corrected.

## Core Requirements Addressed

- GitHub username `Flutevishnu`; project folder `tenant-doc-gateway` under
  `extensions/`.
- File uploads MUST be streamed to disk in chunks (never fully in memory) — done
  in `app/services/storage.py`.
- A CONCURRENT idempotency test (two identical requests via `asyncio.gather`,
  asserting only one record) — done in `tests/test_idempotency_concurrent.py`.

## Assumptions made (default chosen, reason)

1. **Auth = hashed API keys** (not JWT). Simplest mechanism that is still real
   for service-to-service; keys are SHA-256 hashed at rest, shown once.
2. **Result delivery = polling always + optional webhook.** The brief allows
   "webhook OR polling"; both is more production-shaped. Webhooks are
   HMAC-signed when `WEBHOOK_SIGNING_SECRET` is set.
3. **Tenant provisioning via an admin endpoint** (`POST /v1/admin/tenants`)
   guarded by `ADMIN_API_KEY`, plus `scripts/seed_tenants.py` for local dev.
   No self-serve signup was specified.
4. **Cross-tenant access returns 404, not 403**, to avoid an existence oracle.
5. **One shared SuperDocs platform key** in env; tenant isolation is enforced in
   OUR DB (SuperDocs sees one account). Our doc/session/job ids map to SuperDocs
   ids per tenant row.
6. **Approvals: local decision is authoritative, then forwarded to SuperDocs
   inline.** A per-item decision is small; we apply it to our row first
   (source of truth), then forward. If forwarding fails we keep the local
   decision and surface `forward_error` rather than crashing. If SuperDocs
   revisions become heavy, this could move to a background job later.
7. **Idempotency is required on costing endpoints** (upload, edit, export,
   decision) and NOT on reads (`GET /jobs/{id}` etc.).
8. **Cost model is an estimate** (`app/services/cost.py`): edit = 1 op, export =
   0 ops, upload = 0 ops; reconciled with any upstream-reported figure. Exact
   billing is authoritative upstream.
- **SuperDocs endpoint paths are centralized constants** in the client, verified
  against https://api.superdocs.app/openapi.json (2026-08-13). Key corrections:
  approve is `POST /v1/chat/{session_id}/approve` (not `/v1/jobs/.../approvals`);
  async chat and export are session-scoped (no `document_id` on those bodies).
10. **Tests use on-disk SQLite** (not `:memory:`) so multiple connections share
    state and the UNIQUE constraint can arbitrate the concurrency race. Prod uses
    Postgres via `docker-compose.yml`.
11. **`SAMPLE_MODE=true` by default** in `.env.example` to protect the free
    10k-operation allowance; bulk/loop expansion should honor
    `SAMPLE_MAX_SECTIONS`.
12. **PROGRESS.md lives inside the project folder** (not the repo root) so we
    never modify anything outside `extensions/Flutevishnu/`.

## Known limitations

- If the process crashes between committing a job and enqueuing it, the job stays
  `queued` without a worker pick-up. A small periodic sweeper that re-enqueues
  stale `queued` jobs would close this gap.

## Verification done

- `pytest` -> 25 passed, with the SuperDocs API mocked and no live key.
- `ruff check .` -> clean.
- `alembic upgrade head` -> applies the initial schema successfully.
- `loadtests/async_load.py` -> 0 errors at 50 concurrent clients, achieving 100 RPS against the live PostgreSQL container.
