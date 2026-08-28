# TASK.md — Agentic Document Intelligence: Project Scaffold

## Collaboration Rules

These rules apply to every task in this list:

1. **Every non-trivial piece of code must have a test written before or alongside it.**
2. **All assumptions must be logged to `PROGRESS.md` before acting on them.**
3. **Files outside the current task's scope must not be modified without prior declaration.**

---

## Scaffold Tasks

### Task 1 — Create `.gitignore`

Create a `.gitignore` at the project root covering Python artefacts, Node artefacts, environment/secrets files, editor/OS artefacts, and `uv` artefacts. `uv.lock` must **not** be gitignored.

**Verification:** File exists at project root and contains entries for `__pycache__/`, `.venv/`, `.env`, `node_modules/`, `.DS_Store`, and `.uv/`.

```bash
test -f .gitignore && grep -q '__pycache__' .gitignore && echo "PASS"
```

---

### Task 2 — Create `pyproject.toml`

Create `pyproject.toml` at the project root. Set `name`, `version`, and `requires-python = ">=3.11"`. Declare runtime dependencies (`fastapi`, `uvicorn[standard]`, `langgraph`, `psycopg2-binary`, `pgvector`, `sqlalchemy`) and dev dependencies (`pytest`, `httpx`, `anyio[trio]`). Use `hatchling` as the build backend.

**Verification:** `uv sync` completes without errors and a virtual environment is created.

```bash
uv sync
```

---

### Task 3 — Scaffold `src/` package

Create `src/__init__.py` (empty), `src/main.py` with a `FastAPI` app instance and a `GET /health` route returning `{"status": "ok"}`, and `src/README.md` with the one-line description `"Source code for the FastAPI application."`.

**Verification:** The app can be imported and the health route is reachable.

```bash
python -c "from src.main import app; print('PASS')"
```

---

### Task 4 — Scaffold `tests/` package and health test

Create `tests/__init__.py` (empty), `tests/README.md` with the description `"Test suite mirroring the src/ layout."`, and `tests/test_main.py` containing an async test that calls `GET /health` via `httpx.AsyncClient` and asserts `status_code == 200` and body `{"status": "ok"}`.

**Verification:** `uv run pytest` discovers and passes all tests.

```bash
uv run pytest
```

---

### Task 5 — Checkpoint: tests pass

Run the full test suite and confirm every test passes with exit code 0. Resolve any failures before proceeding to Task 6.

**Verification:** `uv run pytest` returns exit code 0.

```bash
uv run pytest; echo "Exit code: $?"
```

---

### Task 6 — Create `Dockerfile`

Create a `Dockerfile` at the project root using `python:3.11-slim` as the base image. Set `WORKDIR /app`, install `uv` via pip, copy `pyproject.toml` and run `uv sync --no-dev`, then copy `src/` and set the default `CMD` to start `uvicorn src.main:app` on `0.0.0.0:8000`.

**Verification:** Docker image builds successfully.

```bash
docker build -t agentic-doc-intelligence .
```

---

### Task 7 — Create `docker-compose.yml`

Create `docker-compose.yml` at the project root. Define a `postgres` service (image `pgvector/pgvector:pg16`, env vars `POSTGRES_USER/PASSWORD/DB`, port 5432, named volume `pgdata`) and an `api` service (builds from `Dockerfile`, port 8000, `depends_on: [postgres]`). Declare the named volume `pgdata`.

**Verification:** Both services start without errors.

```bash
docker compose up
```

---

### Task 8 — Create `TASK.md`

Create this file (`TASK.md`) at the project root listing all scaffold tasks as numbered, individually verifiable increments and embedding the three collaboration rules above.

**Verification:** File exists and contains all task entries and verification steps.

```bash
test -f TASK.md && grep -q 'Collaboration Rules' TASK.md && echo "PASS"
```

---

### Task 9 — Create `PROGRESS.md`

Create `PROGRESS.md` at the project root. Display the project start date `2026-08-08` and include an Assumptions Log table with columns `Date`, `Assumption`, and `Reasoning` and no initial data rows.

**Verification:** File exists with the start date and the Assumptions Log table header.

```bash
test -f PROGRESS.md && grep -q 'Assumptions Log' PROGRESS.md && echo "PASS"
```

---

### Task 10 — Create `docs/invariants.md` and `frontend/README.md`

Create `docs/invariants.md` containing only the heading `# Invariants` (no body content). Create `frontend/README.md` with the one-line description `"Frontend application placeholder."`.

**Verification:** Both files exist.

```bash
test -f docs/invariants.md && test -f frontend/README.md && echo "PASS"
```

---

### Task 11 — Final Checkpoint

Run the full test suite and build the Docker image to confirm the scaffold is complete and all pieces integrate correctly.

**Verification:** `uv run pytest` passes and `docker compose build` succeeds.

```bash
uv run pytest && docker compose build && echo "Scaffold complete"
```
