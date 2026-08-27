# Setup and deployment

## Local offline mode

```bash
cd backend
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
PYTHONPATH=. uvicorn app.main:app --reload
```

No API key is required. SQLite stores local metadata in `release_readiness.db`, ignored by Git.

## PostgreSQL/pgvector mode

Set `DATABASE_URL` to a PostgreSQL URL and apply `backend/migrations/001_pgvector.sql`. The recommended database image is `pgvector/pgvector:pg16`; do not put its password in source control. A production deployment should run migrations as a separate release step and use managed backups.

## React

```bash
cd frontend
npm install
VITE_API_URL=http://127.0.0.1:8000 npm run dev
```

## Deployment options

1. Local Docker Compose for evaluation: API, worker, PostgreSQL/pgvector, object storage, and React static assets.
2. Private staging: separate API and worker containers, managed PostgreSQL, private object storage, internal ingress, and a secret manager.
3. Production: autoscaled workers, point-in-time database recovery, OIDC/SSO, audit retention, tenant quotas, private networking, and monitored queue leases.

No deployment or external account is created by this project.
