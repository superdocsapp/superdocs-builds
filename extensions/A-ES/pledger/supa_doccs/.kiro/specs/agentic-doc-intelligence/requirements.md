# Requirements Document

## Introduction

This feature establishes the project skeleton for an agentic document-intelligence system targeting synthetic microfinance and consumer loan agreements in the Financial Compliance & Credit Auditing domain. The scaffold must be fully runnable from a single command, contain no business logic, and provide clear structural foundations for every subsequent development task. All structure, tooling, and process artefacts are defined here so that no future task needs to re-establish project conventions.

## Glossary

- **Project Root**: The directory `/Users/user/Documents/supa_doccs/` that contains all project files.
- **Scaffold**: The complete set of directories, placeholder files, configuration files, and tooling manifests that constitute the runnable project skeleton before any business logic is added.
- **uv**: The Python package and environment manager used to install dependencies and run commands (`uv run`).
- **LangGraph**: The graph-based agent orchestration framework used to define, run, and checkpoint multi-step AI workflows.
- **pgvector**: A PostgreSQL extension that adds vector similarity search capabilities.
- **TASK.md**: The authoritative ordered list of small, verifiable development increments for the project.
- **PROGRESS.md**: A living log that records today's date and an Assumptions Log table tracking every assumption made during development.
- **docker-compose.yml**: The single-command orchestration file that starts both the PostgreSQL+pgvector service and the FastAPI service.
- **Placeholder README**: A one-line markdown file placed in each empty directory to make the directory trackable by git.
- **Invariants**: Structural or domain rules that must remain true across all versions of the system, recorded in `docs/invariants.md`.

---

## Requirements

### Requirement 1: Python Tooling and Runtime Configuration

**User Story:** As a developer, I want the project to use Python 3.11+ managed by `uv` with all core dependencies declared, so that any contributor can reproduce the environment with a single command.

#### Acceptance Criteria

1. THE Scaffold SHALL include a `pyproject.toml` at the Project Root that specifies `requires-python = ">=3.11"`.
2. THE Scaffold SHALL declare `fastapi`, `uvicorn`, `langgraph`, `psycopg2-binary`, `pgvector`, and `sqlalchemy` as runtime dependencies in `pyproject.toml`.
3. THE Scaffold SHALL declare `pytest` as a development dependency in `pyproject.toml`.
4. WHEN a developer runs `uv sync`, THE Scaffold SHALL install all declared dependencies into an isolated virtual environment without manual setup steps.

---

### Requirement 2: FastAPI Application Entry Point

**User Story:** As a developer, I want a minimal FastAPI application entry point under `src/`, so that the API process can start without errors before any business logic is implemented.

#### Acceptance Criteria

1. THE Scaffold SHALL contain a file at `src/main.py` that instantiates a `FastAPI` application object.
2. WHEN the FastAPI application is started via `uvicorn src.main:app`, THE FastAPI Application SHALL respond to `GET /health` with HTTP status 200.
3. THE `src/` directory SHALL contain a `__init__.py` file making it a Python package.
4. THE `src/` directory SHALL contain a `README.md` with a one-line description of the directory's purpose.

---

### Requirement 3: Test Infrastructure

**User Story:** As a developer, I want a `tests/` directory structured to mirror `src/`, so that every source module has a corresponding test file reachable by `uv run pytest`.

#### Acceptance Criteria

1. THE Scaffold SHALL contain a `tests/` directory at the Project Root.
2. THE `tests/` directory SHALL contain a `__init__.py` file.
3. THE `tests/` directory SHALL contain a `README.md` with a one-line description of the directory's purpose.
4. THE Scaffold SHALL contain a `tests/test_main.py` file with at least one passing test that verifies the `/health` endpoint returns HTTP status 200.
5. WHEN a developer runs `uv run pytest`, THE Test Runner SHALL discover and execute all tests in `tests/` without configuration errors.

---

### Requirement 4: PostgreSQL + pgvector Docker Compose Service

**User Story:** As a developer, I want a `docker-compose.yml` that brings up PostgreSQL with the pgvector extension and the FastAPI service together, so that the full runtime environment starts with one command and requires no manual setup.

#### Acceptance Criteria

1. THE Scaffold SHALL include a `docker-compose.yml` at the Project Root defining a `postgres` service using an image that bundles the pgvector extension (e.g., `pgvector/pgvector:pg16`).
2. THE `docker-compose.yml` SHALL define a `api` service that builds from a `Dockerfile` at the Project Root and depends on the `postgres` service.
3. THE `postgres` service SHALL expose port 5432 and persist data using a named Docker volume.
4. THE `api` service SHALL expose port 8000.
5. WHEN a developer runs `docker compose up`, THE Docker Compose Orchestrator SHALL start both services without requiring any manual steps beyond the command.
6. THE Scaffold SHALL include a `Dockerfile` at the Project Root that uses a Python 3.11 base image and installs dependencies via `uv`.

---

### Requirement 5: TASK.md — Ordered Verifiable Increments

**User Story:** As a developer, I want a `TASK.md` at the Project Root listing small, verifiable development tasks with explicit test requirements, so that progress can be tracked and each task can be verified independently.

#### Acceptance Criteria

1. THE Scaffold SHALL include a `TASK.md` file at the Project Root.
2. THE `TASK.md` SHALL list tasks as individually numbered increments, each small enough to complete in one focused session.
3. EACH task entry in `TASK.md` SHALL specify a verification step (test command or observable output) that confirms the task is complete.
4. THE `TASK.md` SHALL include the instruction that every non-trivial piece of code must have a test written before or alongside it.
5. THE `TASK.md` SHALL include the instruction that assumptions must be logged to `PROGRESS.md` before acting on them.
6. THE `TASK.md` SHALL include the instruction that files outside the current task's scope must not be modified without prior declaration.

---

### Requirement 6: PROGRESS.md — Assumptions Log

**User Story:** As a developer, I want a `PROGRESS.md` at the Project Root pre-populated with today's date and an empty Assumptions Log table, so that all assumptions are recorded in a single, consistent place from day one.

#### Acceptance Criteria

1. THE Scaffold SHALL include a `PROGRESS.md` file at the Project Root.
2. THE `PROGRESS.md` SHALL display the date `2026-08-08` as the project start date.
3. THE `PROGRESS.md` SHALL contain an Assumptions Log table with the columns `Date`, `Assumption`, and `Reasoning` and no data rows initially.

---

### Requirement 7: docs/invariants.md — Header Only

**User Story:** As a developer, I want a `docs/invariants.md` file containing only a header, so that a dedicated place exists to record structural and domain invariants as the system evolves.

#### Acceptance Criteria

1. THE Scaffold SHALL include a `docs/` directory at the Project Root.
2. THE Scaffold SHALL include a `docs/invariants.md` file containing only a top-level markdown heading and no body content.

---

### Requirement 8: .gitignore Coverage

**User Story:** As a developer, I want a `.gitignore` that excludes Python artefacts, Node artefacts, environment files, and secrets, so that no sensitive or generated files are accidentally committed.

#### Acceptance Criteria

1. THE Scaffold SHALL include a `.gitignore` file at the Project Root.
2. THE `.gitignore` SHALL exclude Python bytecode and cache directories (`__pycache__/`, `*.pyc`, `*.pyo`, `.venv/`, `*.egg-info/`, `dist/`, `build/`).
3. THE `.gitignore` SHALL exclude Node artefacts (`node_modules/`, `dist/`, `*.log`).
4. THE `.gitignore` SHALL exclude environment and secrets files (`.env`, `.env.*`, `*.key`, `*.pem`, `secrets/`).
5. THE `.gitignore` SHALL exclude common editor and OS artefacts (`.DS_Store`, `.idea/`, `.vscode/`).
6. THE `.gitignore` SHALL exclude `uv` artefacts (`.uv/`, `uv.lock` is kept intentionally — it SHALL NOT be gitignored).

---

### Requirement 9: Frontend Placeholder

**User Story:** As a developer, I want an empty `frontend/` directory tracked by git with a placeholder README, so that the directory exists and its purpose is clear before any frontend work begins.

#### Acceptance Criteria

1. THE Scaffold SHALL include a `frontend/` directory at the Project Root.
2. THE `frontend/` directory SHALL contain a `README.md` with a one-line description of the directory's purpose.

---

### Requirement 10: No Business Logic in Scaffold

**User Story:** As a developer, I want the scaffold to contain zero business logic, so that the initial structure is unambiguous and the domain layer can be introduced in clearly scoped subsequent tasks.

#### Acceptance Criteria

1. THE Scaffold SHALL NOT contain any document-parsing, compliance-checking, vector-embedding, or LangGraph workflow implementation code.
2. THE `src/` directory SHALL contain only the FastAPI entry point, package init files, and placeholder files at scaffold time.
3. IF a file in the Scaffold contains code beyond imports and a minimal health-check handler, THEN THE Scaffold SHALL be considered incomplete and the file SHALL be revised to remove the excess logic.
