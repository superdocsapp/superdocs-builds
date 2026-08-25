# Deployment

Vercel for the frontend, Render for the backend. Every integration is selected by
configuration, so a deployment can start fully local and adopt real services one at a time.

---

## Frontend (Vercel)

1. Import the repository. Keep the project root as the repository root — `vercel.json`
   handles the rest.
2. Set:

```env
VITE_API_BASE_URL=https://your-render-service.onrender.com
VITE_CLERK_PUBLISHABLE_KEY=pk_live_...
```

Both are baked into the bundle at build time. Changing either requires a redeploy, not just
a restart.

Only `VITE_*` variables reach the browser. Never put a secret behind that prefix.

---

## Backend (Render)

Create a Blueprint from `render.yaml`, or a Web Service manually:

- **Root directory:** `backend`
- **Build:** `pip install -r requirements.txt`
- **Start:** `uvicorn app.main:app --host 0.0.0.0 --port $PORT`

### Required

```env
FRONTEND_ORIGIN=https://your-vercel-app.vercel.app
SESSION_SECRET=<long random string>
```

`FRONTEND_ORIGIN` is the CORS allowlist and must match the deployed frontend origin
exactly, scheme included. If it is wrong, every browser request fails before reaching a
route. Use `ADDITIONAL_CORS_ORIGINS` (comma separated) for preview domains.

`SESSION_SECRET` must be set explicitly. Left blank, each instance generates its own under
`STORAGE_DIR`, and tokens issued by one instance are rejected by another.

### Recommended

```env
CLERK_SECRET_KEY=sk_live_...
NEON_DATABASE_URL=postgresql://...
S3_ENDPOINT_URL=https://gateway.storjshare.io
S3_ACCESS_KEY_ID=...
S3_SECRET_ACCESS_KEY=...
S3_BUCKET_NAME=...
SUPERDOCS_MODE=live
SUPERDOCS_API_KEY=sk_...
SUPERDOCS_BASE_URL=https://api.superdocs.app/v1
```

---

## Persistence

Choose **one** of these. They are not interchangeable after go-live.

### Postgres + object storage (recommended)

Set `NEON_DATABASE_URL` and the three required `S3_*` variables. State and bytes both live
off the instance, so the service is stateless, survives redeploys, and can scale past one
instance.

**Host the database in the region nearest your users.** Round-trip time is the dominant
cost in this system — application CPU is effectively zero, and a one-row query still costs
one round trip. A distant region adds ~300 ms to *every* read.

`psycopg-pool` is required and pinned in `requirements.txt`. Without pooling, each query
pays a fresh TCP + TLS + auth handshake — measured at ~1,890 ms against a remote instance,
roughly 86% of every database call.

### SQLite + local disk (single instance only)

```env
DATABASE_URL=sqlite:////var/data/close_pack.db
STORAGE_DIR=/var/data/storage
```

`render.yaml` mounts a 1 GB disk at `/var/data`. **Without a mounted disk the database,
uploads and exports are on ephemeral storage and are destroyed on every restart and
redeploy.**

SQLite is single-writer: run exactly one instance. Multiple Render instances would each
have their own disk and diverge.

---

## SuperDocs

`SUPERDOCS_MODE=mock` runs entirely offline with no key and no network access, and is the
right setting for review and demo deployments. It implements the same protocol and produces
the same ledger entries as live mode.

For the real API:

```env
SUPERDOCS_MODE=live
SUPERDOCS_API_KEY=sk_...
SUPERDOCS_BASE_URL=https://api.superdocs.app/v1
```

The base URL must include `/v1`. Verify a key cheaply with `GET /v1/sessions`, which
consumes no operations — not `/v1/users/*`, which accepts web-app session tokens only and
returns `401` for a valid `sk_` key.

A blank key in live mode is rejected at client construction rather than producing silent
`401`s.

### Capacity

Generation issues one upload per source document plus one model edit, and each approval
batch and export is one further call. Budget operations per close accordingly, and note
that indexing time scales with page count — a several-hundred-page PDF can take minutes.

---

## Pre-production checklist

- [ ] `SESSION_SECRET` set explicitly, not generated per instance
- [ ] `FRONTEND_ORIGIN` matches the deployed frontend exactly
- [ ] Database hosted near your users; `psycopg-pool` installed
- [ ] Object storage configured, or a disk mounted and exactly one instance running
- [ ] `CLERK_SECRET_KEY` set — this also disables `POST /auth/demo-session`
- [ ] Secrets held in the platform's secret store, never committed
- [ ] `npm test` green: 116 backend, 16 frontend

### Blocking gap

**There is no authorisation model.** Authentication is real; authorisation is absent. Any
signed-in user can approve any change, sign off in any role, and close any period. Add
role checks before this handles anything confidential.

The demo session endpoint issues a token for one fixed identity with no credentials. It is
refused automatically once `CLERK_SECRET_KEY` is set — verify `GET /api/v1/auth/config`
reports `{"mode": "clerk"}` in every deployed environment.

---

## Operating notes

**Logs.** Auth rejections log their real cause server-side while the client sees only
"invalid or expired". SuperDocs failures are recorded in the per-close ledger with
operation, duration and error text.

**A stuck generation** releases after `GENERATION_TIMEOUT_SECONDS` (default 900).

**Restarts are safe.** Pooled connections are returned on shutdown; a generation in flight
is recovered by the timeout above rather than by redelivery.

**Rollback.** No migrations exist — `init_db()` issues `CREATE TABLE IF NOT EXISTS` against
two tables — so rolling the service back is a redeploy. This stops being true the moment
the close document is decomposed into real tables.
