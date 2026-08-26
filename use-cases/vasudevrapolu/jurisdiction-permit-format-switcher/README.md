# Full-Stack AI Engineer Round 2 — Document Intelligence + Permit Switcher

This repository contains the two engineer-lane deliverables:

1. `backend/` — Task 1: an agentic document analyst that ingests a pile, extracts facts, detects conflicts, checks rules, supports resumable runs, human approval, concurrency, and cost/time reporting.
2. `use-cases/jurisdiction-permit-format-switcher/` — Task 2 assigned build: a jurisdiction-aware solar permit packet switcher built on the SuperDocs API, with deterministic local fallback data so the demo and tests do not require a live key.
3. `frontend/` — React review interface for both workflows.

## Target stack

- Python + FastAPI
- LangGraph orchestration
- PostgreSQL + pgvector
- React + Vite
- SuperDocs REST API adapter
- MCP-compatible machine interface
- Docker Compose for local PostgreSQL

## Important honesty boundary

The project uses synthetic solar projects and jurisdiction rules. It does not claim that any jurisdiction template is legally authoritative. A jurisdiction rule is treated as a configuration artifact with a source label, and missing/unsupported requirements are surfaced rather than guessed.

## Quick start

### 1. Start PostgreSQL

```bash
docker compose up -d db
```

### 2. Backend

```bash
cd backend
python -m venv .venv
# Windows PowerShell
.venv\Scripts\Activate.ps1
# macOS/Linux
# source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env   # Windows
# cp .env.example .env   # macOS/Linux
uvicorn app.main:app --reload
```

### 3. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open the Vite URL shown in the terminal.

### 4. Tests

```bash
cd backend
pytest -q
```

Tests use deterministic adapters and do not require a live SuperDocs key.

## Optional SuperDocs integration

Set `SUPERDOCS_API_KEY` in `backend/.env`. The browser never receives this key. The backend calls the SuperDocs server-side API. The permit switcher sends HTML + an instruction and receives updated HTML. Export is handled locally for the synthetic demo and can be replaced with the SuperDocs export endpoint when desired.

## Assigned build demo

The UI lets you:

- enter one solar project record once;
- select jurisdiction A or B;
- generate a packet from the same record;
- see jurisdiction-specific forms, notes, attachments and signature blocks;
- see missing/unsatisfiable requirements as explicit gaps;
- view a submission checklist;
- switch jurisdiction without re-entering the project;
- compare two jurisdiction outputs side by side.

The sample jurisdictions intentionally differ to make the acceptance criterion obvious.

## Task 1 agentic workflow

The workflow is visible as:

`ingest → extract → reconcile → compliance → plan update → human review → commit`

It checkpoints stage state in the repository layer so a stopped run can resume. A run can retry, escalate, or stop on a conflict. Source text containing instructions aimed at the system is recorded as data and never executed as a command.

## Machine interface

The FastAPI endpoints under `/api/agent/*` expose the workflow to another program. Approval is an explicit API operation, so the human gate is not UI-only.

## What to record in the final write-up

- Which source formats/domains are supported.
- What is deterministic vs SuperDocs-backed.
- What was cut and why.
- Test evidence for resume, concurrency, prompt-injection-as-data, and missing-data honesty.
- Measured stage timings and any live integration observations.
