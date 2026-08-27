# Release Readiness Analyst

Release Readiness Analyst turns release artifacts into a cited, reviewable readiness brief. It accepts requirements, design documents, meeting notes, sprint reports, test evidence, and release checklists; maps findings back to source provenance; highlights contradictions and missing evidence; applies explicit release rules; and waits for item-level human decisions before completing a report.

This is a separate project from `extensions/Madhumasa84/sdx`. It is intentionally deterministic and offline by default. No credentials, buyer contact, or paid/live model operation is required for the demo or test suite.

## Status

The first implementation milestone includes:

- FastAPI service boundaries.
- A persisted staged workflow equivalent to a LangGraph state machine.
- SQLite offline fixtures plus a PostgreSQL/pgvector production migration path.
- Source SHA-256 provenance, line citations, immutable chunks, and deterministic embeddings.
- Contradiction, missing-evidence, coverage, and prompt-injection findings.
- Durable checkpoints, interruption injection, resume, leases, and same-run locking.
- Item-level approve/reject/request-more-evidence decisions.
- Incremental source invalidation and report revisions.
- MCP-compatible, schema-validated machine operations.
- React UI showing stage progress, cited findings, decisions, and report JSON.

The task PDF was not available at implementation time in this environment; PDF-specific scoring and submission clauses must be checked before release.

## Quick start

```bash
cd backend
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

In another terminal:

```bash
cd frontend
npm install
npm run dev
```

The backend uses SQLite when `DATABASE_URL` is omitted. Production uses PostgreSQL with the `backend/migrations/001_pgvector.sql` migration and a pgvector-enabled database. Copy `.env.example` to `.env`; it contains no secrets.

## API journey

```bash
run=$(curl -s -X POST http://127.0.0.1:8000/runs \
  -H 'content-type: application/json' \
  -d '{"workspace_id":"demo","title":"Q3 release readiness"}' | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')
curl -s -X POST "http://127.0.0.1:8000/runs/$run/sources" -F file=@fixtures/requirements.md
curl -s -X POST "http://127.0.0.1:8000/runs/$run/sources" -F file=@fixtures/test-evidence.md
curl -s -X POST "http://127.0.0.1:8000/runs/$run/execute"
curl -s "http://127.0.0.1:8000/runs/$run"
```

The execute response remains `awaiting_decisions` when critical findings exist. Submit every required item explicitly:

```json
{"decisions":[{"finding_id":"fnd_...","state":"approved"},{"finding_id":"fnd_...","state":"rejected","feedback":"Attach the missing test log."}]}
```

## Security posture

Source documents are untrusted data. Instruction-like text is recorded as a security finding and never executed. Credentials, signed URLs, source bytes, and private prompts are not logged. See [docs/THREAT-MODEL.md](docs/THREAT-MODEL.md).

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Setup and deployment](docs/SETUP.md)
- [Threat model](docs/THREAT-MODEL.md)
- [Three-minute demo](docs/DEMO.md)
- [Submission checklist](docs/SUBMISSION-CHECKLIST.md)

