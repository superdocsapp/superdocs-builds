# Implementation Plan: agentic-doc-intelligence — Project Scaffold

## Overview

Create the complete project skeleton for the agentic document-intelligence system. Every task produces a concrete file or set of files; no business logic is introduced. The scaffold is complete when `uv run pytest` passes and `docker compose up` starts both services.

Language: Python 3.11 / YAML / TOML / Dockerfile

---

## Tasks

- [x] 1. Create `.gitignore`
  - [x] 1.1 Write `.gitignore` at the project root
    - Cover Python artefacts: `__pycache__/`, `*.pyc`, `*.pyo`, `.venv/`, `*.egg-info/`, `dist/`, `build/`
    - Cover Node artefacts: `node_modules/`, `*.log`
    - Cover env / secrets: `.env`, `.env.*`, `*.key`, `*.pem`, `secrets/`
    - Cover editor / OS: `.DS_Store`, `.idea/`, `.vscode/`
    - Cover uv artefacts: `.uv/` — `uv.lock` must NOT be gitignored
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6_

- [x] 2. Create `pyproject.toml`
  - [x] 2.1 Write `pyproject.toml` at the project root
    - Set `name = "agentic-doc-intelligence"`, `version = "0.1.0"`, `requires-python = ">=3.11"`
    - Declare runtime deps: `fastapi`, `uvicorn[standard]`, `langgraph`, `psycopg2-binary`, `pgvector`, `sqlalchemy`
    - Declare dev deps (`[project.optional-dependencies] dev`): `pytest`, `httpx`, `anyio[trio]`
    - Set build system to hatchling
    - _Requirements: 1.1, 1.2, 1.3_

- [x] 3. Scaffold `src/` package
  - [x] 3.1 Create `src/__init__.py` (empty)
    - _Requirements: 2.3_
  - [x] 3.2 Create `src/main.py` with FastAPI app and `/health` route
    - Import `FastAPI` only; instantiate `app = FastAPI()`
    - Add `@app.get("/health") async def health() -> dict: return {"status": "ok"}`
    - No other logic, imports, or routes
    - _Requirements: 2.1, 2.2, 10.1, 10.2, 10.3_
  - [x] 3.3 Create `src/README.md`
    - Content: `"Source code for the FastAPI application."`
    - _Requirements: 2.4_

- [x] 4. Scaffold `tests/` package and health test
  - [x] 4.1 Create `tests/__init__.py` (empty)
    - _Requirements: 3.1, 3.2_
  - [x] 4.2 Create `tests/test_main.py` with async health-endpoint test
    - Import `pytest`, `httpx`, and `app` from `src.main`
    - Use `httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")`
    - Assert `response.status_code == 200` and `response.json() == {"status": "ok"}`
    - Mark with `@pytest.mark.anyio`
    - _Requirements: 3.4, 3.5_
  - [ ]* 4.3 Write property test for health endpoint
    - **Property 1: Health endpoint always returns 200**
    - Send arbitrary GET requests to `/health`; assert status 200 and body `{"status": "ok"}` every time
    - **Validates: Requirements 2.2, 3.4**
  - [x] 4.4 Create `tests/README.md`
    - Content: `"Test suite mirroring the src/ layout."`
    - _Requirements: 3.3_

- [x] 5. Checkpoint — tests must pass
  - Run `uv run pytest` and confirm all tests pass. Ask the user if any test fails or if questions arise.

- [x] 6. Create `Dockerfile`
  - [x] 6.1 Write `Dockerfile` at the project root
    - Base image: `python:3.11-slim`; `WORKDIR /app`
    - Install `uv` via `pip install --no-cache-dir uv`
    - Copy `pyproject.toml`, run `uv sync --no-dev` (dependency-cache layer)
    - Copy `src/` into `./src/`
    - `CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]`
    - _Requirements: 4.6_

- [x] 7. Create `docker-compose.yml`
  - [x] 7.1 Write `docker-compose.yml` at the project root
    - Define `postgres` service: image `pgvector/pgvector:pg16`, env vars `POSTGRES_USER/PASSWORD/DB`, port 5432, named volume `pgdata`
    - Define `api` service: `build: .`, port 8000, `depends_on: [postgres]`
    - Declare named volume `pgdata`
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5_

- [x] 8. Create `TASK.md`
  - [x] 8.1 Write `TASK.md` at the project root
    - List all scaffold tasks as numbered, individually verifiable increments
    - Each entry must include a verification step (test command or observable output)
    - Embed the three collaboration rules:
      1. Every non-trivial piece of code must have a test written before or alongside it.
      2. All assumptions must be logged to `PROGRESS.md` before acting on them.
      3. Files outside the current task's scope must not be modified without prior declaration.
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6_

- [x] 9. Create `PROGRESS.md`
  - [x] 9.1 Write `PROGRESS.md` at the project root
    - Display project start date: `2026-08-08`
    - Include an Assumptions Log table with columns `Date`, `Assumption`, `Reasoning` and no data rows
    - _Requirements: 6.1, 6.2, 6.3_

- [x] 10. Create `docs/invariants.md` and `frontend/README.md`
  - [x] 10.1 Create `docs/invariants.md`
    - Content: `# Invariants` (heading only, no body)
    - _Requirements: 7.1, 7.2_
  - [x] 10.2 Create `frontend/README.md`
    - Content: `"Frontend application placeholder."`
    - _Requirements: 9.1, 9.2_

- [x] 11. Final checkpoint — full verification
  - Run `uv run pytest`; confirm all tests pass.
  - Run `docker compose build` and confirm the image builds without errors.
  - Ensure all scaffold files listed in the directory layout exist.
  - Ask the user if questions arise before proceeding to domain tasks.

---

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP.
- Each task references specific requirements for traceability.
- Checkpoints ensure incremental validation after each logical group.
- Property 1 is the only correctness property defined for the scaffold; its test belongs alongside the unit tests in task 4.
- No business logic of any kind may be introduced in these tasks — all files are structural or configuration artefacts.

---

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["2.1"] },
    { "id": 2, "tasks": ["3.1", "3.2", "3.3"] },
    { "id": 3, "tasks": ["4.1", "4.4"] },
    { "id": 4, "tasks": ["4.2", "6.1", "8.1", "9.1", "10.1", "10.2"] },
    { "id": 5, "tasks": ["4.3", "7.1"] }
  ]
}
```
