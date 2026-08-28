# Design Document

## Feature: agentic-doc-intelligence — Project Scaffold

---

## Overview

This document describes the structural design of the project scaffold for the agentic document-intelligence system. The scaffold provides no business logic; its sole purpose is to establish a fully runnable, reproducible project skeleton that all subsequent work builds on.

The system targets synthetic microfinance and consumer loan-agreement documents in the Financial Compliance & Credit Auditing domain. All domain logic (parsing, embedding, compliance checks, LangGraph workflows) is out of scope for this scaffold.

---

## Architecture

```
/Users/user/Documents/supa_doccs/          ← Project Root
├── pyproject.toml                         # uv-managed Python project manifest
├── Dockerfile                             # Python 3.11-slim API container
├── docker-compose.yml                     # Orchestrates postgres + api services
├── TASK.md                                # Ordered verifiable development increments
├── PROGRESS.md                            # Start date + Assumptions Log
├── .gitignore                             # Python / Node / env / editor exclusions
├── README.md                              # (existing) top-level project overview
├── decisions.md                           # (existing) architectural decision log
├── src/
│   ├── __init__.py
│   ├── main.py                            # FastAPI app, GET /health only
│   └── README.md                          # "Source code for the FastAPI application."
├── tests/
│   ├── __init__.py
│   ├── test_main.py                       # /health → 200 test
│   └── README.md                          # "Test suite mirroring the src/ layout."
├── docs/
│   └── invariants.md                      # Header only: # Invariants
└── frontend/
    └── README.md                          # "Frontend application placeholder."
```

The architecture is flat and conventional:
- `src/` is a Python package (`__init__.py`) importable as `src.main`.
- `tests/` mirrors `src/` so every source module has a sibling test file.
- `docs/` holds persistent project knowledge (invariants, decisions).
- All empty directories carry a `README.md` so git tracks them without `.gitkeep` files.

---

## Components and Interfaces

### Component 1: `pyproject.toml`

Managed by `uv`. Declares project metadata and all runtime + dev dependencies.

```toml
[project]
name = "agentic-doc-intelligence"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi",
    "uvicorn[standard]",
    "langgraph",
    "psycopg2-binary",
    "pgvector",
    "sqlalchemy",
]

[dependency-groups]
dev = [
    "pytest",
    "httpx",
    "anyio[trio]",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

A developer runs `uv sync` to reproduce the full environment with no additional steps.

---

### Component 2: `src/main.py` — FastAPI Entry Point

Minimal application object plus a single `/health` route. No imports beyond `fastapi`.

```python
from fastapi import FastAPI

app = FastAPI()


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
```

Started via: `uvicorn src.main:app --host 0.0.0.0 --port 8000`

**Interface exposed:**

| Method | Path | Response | Description |
|--------|------|----------|-------------|
| GET | `/health` | `{"status": "ok"}` (HTTP 200) | Liveness check |

No authentication, no request body, no query parameters at scaffold stage.

---

### Component 3: `tests/test_main.py`

Uses `httpx.AsyncClient` with ASGI transport to exercise the live app object without starting a network server.

```python
import pytest
import httpx
from src.main import app


@pytest.mark.anyio
async def test_health_returns_200():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

Run with: `uv run pytest`

---

### Component 4: `Dockerfile`

Python 3.11-slim base. `uv` installed via pip, then dependencies synced before source is copied — enabling Docker layer cache hits on repeated builds that only change source.

```dockerfile
FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml .
RUN uv sync --no-dev

COPY src/ ./src/

CMD ["uv", "run", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

---

### Component 5: `docker-compose.yml`

Two services. `api` waits for `postgres` before starting. Data persists in named volume `pgdata` across container restarts.

```yaml
version: "3.9"

services:
  postgres:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
      POSTGRES_DB: docdb
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data

  api:
    build: .
    ports:
      - "8000:8000"
    depends_on:
      - postgres

volumes:
  pgdata:
```

Single-command startup: `docker compose up`

Key decisions:
- `pgvector/pgvector:pg16` bundles the extension — no init script needed to `CREATE EXTENSION vector`.
- Named volume `pgdata` persists data across `docker compose down` / `up` cycles.

---

### Component 6: Process Artefacts

**`TASK.md`** — Collaboration contract. Tasks are small, individually verifiable increments. Each entry includes a verification command or observable output. Embedded rules:
- Every non-trivial piece of code must have a test before or alongside it.
- All assumptions must be logged to `PROGRESS.md` before acting on them.
- Files outside the current task's scope must not be modified without prior declaration.

**`PROGRESS.md`** — Project start date `2026-08-08` with an empty Assumptions Log table (columns: Date, Assumption, Reasoning).

**`docs/invariants.md`** — Contains only `# Invariants`. Populated as structural and domain rules are identified.

**`.gitignore`** — Covers four categories:

| Category | Patterns |
|----------|----------|
| Python artefacts | `__pycache__/`, `*.pyc`, `*.pyo`, `.venv/`, `*.egg-info/`, `dist/`, `build/` |
| Node artefacts | `node_modules/`, `*.log` |
| Env / secrets | `.env`, `.env.*`, `*.key`, `*.pem`, `secrets/` |
| Editor / OS | `.DS_Store`, `.idea/`, `.vscode/` |
| uv artefacts | `.uv/` |

`uv.lock` is intentionally **not** gitignored — lock files must be committed for reproducibility.

---

## Data Models

No data models at scaffold stage. Database schema, ORM models, and vector store configuration are introduced in subsequent tasks.

---

## Error Handling

At scaffold stage, error handling is limited to FastAPI's built-in responses:
- Unmatched routes → 404 JSON (FastAPI default).
- Unhandled exceptions → 500 JSON (FastAPI default).
- Invalid request bodies → 422 JSON (Pydantic validation, FastAPI default).

Custom exception handlers are introduced when business-logic routes are added.

---

## Testing Strategy

Two complementary layers:

**Smoke tests** — Verify that every required file and directory exists with the correct structure (pyproject.toml fields, .gitignore patterns, directory layout). These are lightweight assertions that run as part of `uv run pytest` and catch scaffold regressions immediately.

**Example-based unit tests** — Verify deterministic endpoint behavior with concrete inputs. `tests/test_main.py` exercises `GET /health` using `httpx.AsyncClient` with ASGI transport — no live server, no network, fast execution.

Property-based testing is not applicable to this scaffold: there are no pure functions with parameterisable input spaces. The correctness properties below are stated as invariants enforced by the example and smoke tests.

---

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

**Property reflection:** After analysing all 10 requirements and their acceptance criteria, the scaffold contains no pure business-logic functions with varying inputs. The only testable functional behavior is the `/health` endpoint (deterministic, covered by example test). Two additional universal properties emerge from the structure requirements: every TASK.md entry must carry a verification step (Req 5.3), and no src/ file may contain business logic (Req 10.1/10.3).

---

### Property 1: Health endpoint always returns 200

*For any* HTTP GET request sent to the `/health` endpoint of the running FastAPI application, the response SHALL have HTTP status code 200 and a JSON body of `{"status": "ok"}`.

**Validates: Requirements 2.2, 3.4**

---

### Property 2: Every TASK.md entry contains a verification step

*For any* task entry present in `TASK.md`, the entry SHALL contain an explicit verification step — either a runnable test command or a described observable output — that unambiguously confirms the task is complete.

**Validates: Requirements 5.3**

---

### Property 3: No business logic in scaffold source files

*For any* Python file located under `src/` at scaffold time, the file SHALL NOT import or define document-parsing, compliance-checking, vector-embedding, or LangGraph workflow code. The only permitted constructs are standard-library / third-party imports, the FastAPI app instantiation, and the `/health` route handler.

**Validates: Requirements 10.1, 10.2, 10.3**
