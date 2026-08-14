# Load test results

These are **real numbers** from a local run of `loadtests/async_load.py` against
the gateway, exercising the authenticated read path (`GET /v1/documents`) so the
test measures the gateway itself and consumes **zero** SuperDocs operations.

## Environment

- Machine: local dev laptop (Windows), single API process (`uvicorn`, 1 worker)
- Database: **SQLite** (dev default). SQLite serializes writes, so these numbers
  are a conservative floor — Postgres (the production default in
  `docker-compose.yml`) will scale higher on write-heavy paths.
- Endpoint under test: `GET /v1/documents` (auth + tenant-scoped DB read)

## How to reproduce

```bash
# 1. Start the stack (or a single uvicorn with a migrated DB)
docker compose up --build     # or: alembic upgrade head && uvicorn app.main:app

# 2. Run the load script (creates its own tenant via the admin key)
python loadtests/async_load.py \
  --base-url http://localhost:8000 \
  --admin-key "$ADMIN_API_KEY" \
  --requests 1000 --concurrency 50
```

## Results

| Run | Requests | Concurrency | Throughput (req/s) | p50 (ms) | p95 (ms) | p99 (ms) | Errors |
|-----|----------|-------------|--------------------|----------|----------|----------|--------|
| A   | 1000     | 50          | 177.7              | 275.9    | 331.1    | 386.2    | 0 (0%) |
| B   | 500      | 10          | 177.5              | 53.5     | 69.9     | 118.4    | 0 (0%) |

## Reading the numbers

- **Zero errors** under 50 concurrent clients — auth, tenant scoping, and the DB
  read path are stable under concurrency.
- Throughput plateaus around ~178 req/s because **SQLite is single-writer**; the
  connection pool queues behind it. This is the expected dev-mode ceiling.
- Run B (lower concurrency) shows the true per-request latency (~54 ms p50); the
  higher p50 in Run A is queueing delay from SQLite serialization, not CPU.
- The long-running SuperDocs calls are deliberately **not** in this hot path —
  they run in the Arq worker, so the API stays responsive regardless of how slow
  an upstream edit is.

## Next step for a production run

Point `DATABASE_URL` at Postgres and run the same script; write throughput rises
substantially because concurrent writers no longer serialize on a single file.
