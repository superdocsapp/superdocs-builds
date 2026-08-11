# Diligence Q&A Dossier Builder

An agentic startup due diligence pipeline built to ingest mixed-format data rooms, perform vector-based semantic retrieval, validate evidence grounding, detect fact-room contradictions, enforce citation integrity, and coordinate dossier QA runs under LangGraph with durable PostgreSQL state checkpointing and a human-in-the-loop React dashboard.

---

## 1. Project Overview

Acquiring, funding, or auditing a startup requires parsing mixed-format data rooms (financial records, legal docs, pitch decks) to verify diligence claims. The **Diligence Q&A Dossier Builder** automates this by executing structured question-answering workflows against data room contents. The architecture treats LLMs strictly as processors rather than facts sources, establishing a rigid check-and-balance pipeline that prevents hallucinations, flags contradictions, registers citations, pauses for human review under low-confidence conditions, and persists workflow state across process restarts.

---

## 2. Core Capabilities

- **Multi-Format Data Room Ingestion**: Parses PDF, DOCX, XLSX, TXT, MD, and CSV files natively. Explicitly flags legacy formats like `.xls` as unsupported.
- **Deduplication Safeguard**: Automatically calculates SHA-256 hashes of raw file uploads to prevent duplicate parsing and clean up overlapping indices.
- **pgvector Semantic Search**: Stores text chunks with 1536-dimension embeddings inside a PostgreSQL vector database, executing cosine-similarity query matching.
- **Evidence-First Grounding**: Classifies evidence types strictly into `supporting`, `contradicting`, `contextual`, or `insufficient`. Never allows LLM generation without grounded context.
- **Contradiction & Conflict Detection**: Identifies numerical, temporal, or factual discrepancies (e.g. conflicting revenue stats in pitch decks vs tax filings) and routes finding to `conflict` state.
- **Citation Validation**: Resolves each claim against database chunk UUIDs and sanitizes metadata (file, page, section, context excerpt). Prevents prompt-injected hallucinated citations.
- **Prompt-Injection Shielding**: Isolates document text inside XML safety tag structures and constructs strict system schemas, ensuring context is evaluated purely as data rather than instructions.
- **LangGraph Stateful Orchestration**: Organizes execution nodes (Query Analysis &rarr; Retrieval &rarr; Sufficiency &rarr; Conflict Detection &rarr; Answer Generation &rarr; Citation Validation &rarr; Quality Gate &rarr; Human Review &rarr; Finalization).
- **Persistent checkpointer**: Stores state graph variables (thread ID, writes list, channel values, checkpoints) durably in PostgreSQL tables using binary blobs.
- **Human-in-the-Loop Review**: Interrupts the workflow on conflict, quality failures, or low confidence (<60%), presenting the finding for approval, manual edit, or rejection.
- **Audited Runs History**: Preserves historical execution states in `FindingExecutionHistory` on retries, providing a robust governance audit trail.
- **React Dashboard UI**: A modern, dark-theme-first view panel styled with responsive Vanilla CSS mapping stats cards, comparative columns, and workflow paths.

---

## 3. System Architecture

```
                                  ┌──────────────────────────┐
                                  │    React SaaS Frontend   │
                                  └─────────────┬────────────┘
                                                │ API requests / proxy
                                                ▼
                                  ┌──────────────────────────┐
                                  │     FastAPI Backend      │
                                  └──────┬────────────┬──────┘
                                         │            │
                                         ▼            ▼
 ┌──────────────────────────┐     ┌──────────────┐  ┌────────────────────────┐
 │   LangGraph Checkpointer │◄───►│  PostgreSQL  │  │  Ingestion & Parsing   │
 │   (SQLAlchemy Saver)     │     │  (pgvector)  │  │  (PDF/DOCX/XLSX/TXT)   │
 └──────────────────────────┘     └──────────────┘  └────────────────────────┘
                                         ▲
                                         │ LLM Schema Generation
                                         ▼
                                  ┌──────────────┐
                                  │ Mock/Real    │
                                  │ LLM Service  │
                                  └──────────────┘
```

### Execution Pipeline Nodes
1. **Query Analysis**: Clean/normalize the question without mandatory LLM calls.
2. **Retrieval**: Match vector embeddings against pgvector document chunks.
3. **Evidence Sufficiency**: Check score thresholds; short-circuit to `insufficient_evidence` if no matching data is found.
4. **Conflict Detection**: Check retrieved chunks for contradicting facts.
5. **Answer Generation**: Formulate structured answers and note contradictions.
6. **Citation Validation**: Double-check all generated citations against database indices.
7. **Quality Gate**: Validate state properties.
8. **Human Review**: Flag and pause execution if review conditions are met.
9. **Finalization**: Commit the dossier finding.

---

## 4. Technical Stack

- **Backend**: Python 3.13, FastAPI, SQLAlchemy (Asyncio `asyncpg`), Uvicorn
- **Orchestration**: LangGraph, LangChain Core
- **Database**: PostgreSQL 16+ with the `pgvector` extension
- **Frontend**: React 18, TypeScript, Vite, Vanilla CSS (Outfit & Inter fonts)
- **Local Dev Sandbox**: Docker & Docker Compose

---

## 5. API Endpoints

### Documents API (`/api/v1/documents`)
- `POST /upload`: Ingests a data-room file, enforces deduplication, chunks text, and inserts embeddings.
- `GET /`: Lists all ingested documents and their status.
- `DELETE /{document_id}`: Cascade deletes document metadata, chunks, and storage reference.
- `POST /search`: Queries pgvector using semantic cosine-similarity search.

### Dossiers API (`/api/v1/dossiers`)
- `GET /`: Lists all dossiers.
- `POST /`: Creates a new dossier.
- `GET /{dossier_id}`: Retrieves dossier details with nested findings.
- `POST /{dossier_id}/questions`: Appends a batch of questions to a dossier.
- `POST /{dossier_id}/run`: sequential, isolated run loop for pending findings.

### Reviewer API (`/api/v1/dossiers/{dossier_id}/findings/{finding_id}`)
- `POST /approve`: Resumes paused workflow thread.
- `POST /reject`: Rejects the draft finding with a text reason.
- `POST /edit`: Overwrites the answer and reasoning summary, completing review.
- `POST /retry`: Archives current run to execution history and spawns a fresh run thread.

---

## 6. Local Setup & Running

### 1. Prerequisites
- Docker and Docker Compose
- Python 3.13+
- Node.js v22.19+

### 2. Database Environment Setup
Clone the repository and spin up the database container:
```bash
docker compose up -d
```
*Note: The database maps host port `5433` to prevent conflicts with other local databases.*

### 3. Backend Setup
1. Create a Python virtual environment and activate it:
   ```bash
   python -m venv .venv
   # Windows:
   .venv\Scripts\activate
   # macOS/Linux:
   source .venv/bin/activate
   ```
2. Install dependencies:
   ```bash
   pip install -r backend/requirements.txt
   ```
3. Run migrations and start the server:
   ```bash
   python -m uvicorn backend.app.main:app --reload --port 8000
   ```
4. Verify server health at `http://localhost:8000/api/v1/health`.

### 4. Frontend Setup
1. Navigate to the `frontend` folder:
   ```bash
   cd frontend
   ```
2. Install dependencies:
   ```bash
   npm install
   ```
3. Start the dev server:
   ```bash
   npm run dev
   ```
   *Vite routes proxy calls dynamically to `http://localhost:8000`.*
4. Open your browser to `http://localhost:5173`.---

## 7. Testing Strategy & Results

We maintain a rigorous test suite validating the complete ingest-to-checkpointer lifecycle:
- Run backend pytest:
  ```bash
  .venv\Scripts\pytest -vv
  ```
- **Results**: **55/55 tests passing** (including unit, integration, checkpoint-resume, concurrency, prompt-injection, telemetry metrics, MCP, and QA regression tests).
- **Warning Log**: 1 warning present from Starlette/FastAPI TestClient httpx dependency. This represents a third-party warning and does not impact application execution.

---

## 8. Frontend Interface Guide

- **Dashboard**: Displays a visual card count of Total, Running, Completed, Review-Required, and Failed dossiers.
- **Create Dossier**: Lets the user name the dossier and add multiple diligence questions in a preview card before final submission.
- **Dossier Detail**: Displays overall dossier percentage progress and lists findings cards with separate statuses.
- **Finding Review**: 
  - Displays original question, reasoning, and parsed citations (including document, page, and chunk excerpt).
  - **Conflict UX**: Renders a prominent orange conflict alert and maps a side-by-side comparative block separating Supporting Evidence from Contradicting Evidence.
  - **Workflow Progress Bar**: Renders execution stages dynamically.
  - **Action buttons**: Direct Approve, Reject (with reason modal), Edit override, and Retry.
- **Data Room Manager**: Contains a drag-and-drop zone with status logs and cascade deletion commands.

---

## 9. Model Context Protocol (MCP) Server

The application includes an official **Model Context Protocol (MCP) Server** exposing programmatic diligence coordination tools to LLM agents or machine clients.

### Transport
* **Standard Input/Output (stdio)**: Communication runs over standard input and output streams (`stdin`/`stdout`).

### Startup Command
Start the MCP server independently using the active Python virtual environment:
```bash
.venv\Scripts\python mcp_server.py
```

### Available Tools

#### 1. `upload_document`
* **Description**: Ingests a text, markdown, PDF, DOCX, or XLSX document into the startup due diligence data room.
* **Input Schema**:
  ```json
  {
    "type": "object",
    "properties": {
      "filename": {"type": "string", "description": "Name of the file to ingest"},
      "content_base64": {"type": "string", "description": "Base64-encoded file contents"}
    },
    "required": ["filename", "content_base64"]
  }
  ```
* **Success Output Structure**:
  ```json
  {
    "document_id": "uuid-string",
    "filename": "financials.pdf",
    "size": 124950,
    "hash": "sha256-hash-value",
    "ingestion_status": "success",
    "duplicate_status": false
  }
  ```

#### 2. `send_edit_instruction`
* **Description**: Submits reviewer manual answer and reasoning overrides to resolve a paused finding.
* **Input Schema**:
  ```json
  {
    "type": "object",
    "properties": {
      "dossier_id": {"type": "string", "description": "Dossier UUID"},
      "finding_id": {"type": "string", "description": "Finding UUID"},
      "answer": {"type": "string", "description": "The final edited text answer to store"},
      "reasoning_summary": {"type": "string", "description": "Notes outlining reasoning adjustments"}
    },
    "required": ["dossier_id", "finding_id", "answer", "reasoning_summary"]
  }
  ```
* **Success Output Structure**:
  ```json
  {
    "finding_id": "finding-uuid",
    "status": "answered",
    "review_status": "edited",
    "answer": "Grounded compliance posture is SOC2 compliant.",
    "reasoning_summary": "Reviewed updated documentation."
  }
  ```

#### 3. `approve_proposed_changes`
* **Description**: Approves a proposed finding, clearing its review check and resuming graph thread finalization.
* **Input Schema**:
  ```json
  {
    "type": "object",
    "properties": {
      "dossier_id": {"type": "string", "description": "Dossier UUID"},
      "finding_id": {"type": "string", "description": "Finding UUID"}
    },
    "required": ["dossier_id", "finding_id"]
  }
  ```
* **Success Output Structure**:
  ```json
  {
    "finding_id": "finding-uuid",
    "status": "answered",
    "review_status": "approved",
    "approval_result": "success"
  }
  ```

#### 4. `export_result`
* **Description**: Exports the complete dossier report containing questions, answers, citations, and diligence gaps as Markdown.
* **Input Schema**:
  ```json
  {
    "type": "object",
    "properties": {
      "dossier_id": {"type": "string", "description": "Dossier UUID"}
    },
    "required": ["dossier_id"]
  }
  ```
* **Success Output Structure**: Returns the exact raw Markdown string detailing findings, summaries, and warnings.

---

## 10. Cost & Timing Telemetry API

Every stage of a dossier diligence run is instrumented automatically. A telemetry wrapper intercepts node execution, records start/end timestamps, estimates token usage based on text length (`char_count // 4`), and computes configurable cost estimations:
* **Input tokens**: $5.00 / 1M tokens ($0.000005 per token)
* **Output tokens**: $15.00 / 1M tokens ($0.000015 per token)

### Get Dossier Metrics Endpoint
* **Endpoint**: `GET /api/v1/dossiers/{dossier_id}/metrics`
* **Response format**:
  ```json
  {
    "dossier_id": "uuid-string",
    "total_stages": 9,
    "successful_stages": 9,
    "failed_stages": 0,
    "total_duration_ms": 12450,
    "total_input_tokens": 1250,
    "total_output_tokens": 850,
    "total_tokens": 2100,
    "estimated_total_cost": 0.0190,
    "stages": [
      {
        "stage_name": "answer_generation",
        "status": "success",
        "duration_ms": 1250,
        "input_tokens": 800,
        "output_tokens": 450,
        "model_name": "mock-model",
        "provider_name": "mock-provider",
        "estimated_cost": 0.01075,
        "error_message": null
      }
    ]
  }
  ```

---

## 11. Ingestion Performance Benchmark

A reproducible, large-scale performance testing benchmark is included under `tests/benchmark_40_documents.py`. It generates 40 unique corporate files (exceeding 2,500 characters each) with distinct target facts, ingests them into the vector database via the real parsing & embeddings pipeline, and runs fact queries to assert retrieval accuracy and time performance.

### Run Benchmark Command
From the root of the project, run:
```bash
# Windows (PowerShell):
$env:PYTHONPATH="."
.venv\Scripts\python.exe tests/benchmark_40_documents.py

# macOS/Linux:
PYTHONPATH=. .venv/bin/python tests/benchmark_40_documents.py
```
This script clean truncates database documents before execution, outputting file sizes, chunk counts, latency averages, and process peak memory metrics.

---

## 12. Known Limitations & Future Improvements

1. **Mock LLM Adapter**: Currently runs on a mock LLM service tailored to predictable test triggers. It should be configured with a real LLM adapter for production.
2. **Complex Table Parsing**: Spreadsheet extraction currently parses raw rows into strings; a future enhancement would integrate layout-aware parsers for complex nested tables.

---

## 13. Credits

"Built for the SuperDocs Engineer Task — Diligence Q&A Dossier Builder."

