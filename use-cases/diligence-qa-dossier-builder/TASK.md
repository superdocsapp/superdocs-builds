# Task Specifications: Diligence Q&A Dossier Builder

This document serves as the official specification for the Diligence Q&A Dossier Builder, outlining the scope, requirements, technical goals, non-goals, and acceptance criteria.

## 1. Assignment Core Requirements

Build an agentic system that can:
1. Accept startup data room files (10–40 files in mixed formats).
2. Classify the uploaded documents.
3. Extract relevant facts.
4. Perform semantic search and retrieval.
5. Detect and report contradictions/conflicts between sources.
6. Generate a grounded diligence dossier based on standard questions.
7. Provide exact citations (filename, section, page, excerpt) for every claim.
8. Explicitly flag missing/insufficient evidence instead of hallucinating.
9. Support multi-stage observable agent workflows.
10. Support retries, skips, and human escalation/intervention.
11. Support workflow state persistence and resumption.
12. Present findings for human approval/rejection.
13. Ensure rejection of individual findings does not corrupt/discard other approved findings.
14. Expose a machine interface (MCP server) to drive the system programmatically.
15. Protect against prompt injection embedded in source documents.
16. Support concurrent runs without state corruption.
17. Report execution cost and timing breakdown by stage.
18. Run comprehensive tests without requiring live/paid API keys.

---

## 2. Technical Stack

* **Backend**: Python 3.13+, FastAPI
* **Agent Orchestration**: LangGraph, LangChain
* **Database**: PostgreSQL with `pgvector`
* **Frontend**: React, TypeScript, Vanilla CSS
* **Orchestration / Driveability**: MCP (Model Context Protocol) server
* **Infrastructure**: Docker & Docker Compose for local PostgreSQL + pgvector

---

## 3. Goals & Non-Goals

### Goals
- Fully observable multi-stage pipeline.
- Strong source grounding (no un-cited answers).
- Bulletproof prompt injection filtering (treating document content strictly as data).
- Persistent state so that a container/process crash can resume where it left off.
- High-fidelity clean user interface using responsive Vanilla CSS with polished micro-interactions.

### Non-Goals (Out of Scope for initial phases)
- Production deployment scripts for AWS/GCP (Docker Compose is sufficient for local development).
- Dynamic third-party SaaS document integrations (e.g. syncing direct from Google Drive/Dropbox in Phase 1).
- PDF layout parsing of complex multi-column images or scans (text-based formats and standard PDFs are the focus).
- Secondary build "Accessibility-tagged export tool" integration inside the main app. That must remain a separate standalone utility/module.

---

## 4. Acceptance Criteria

- **Phase 1 Acceptance (Completed)**:
  - Root configuration and structure defined.
  - FastAPI app launches, responds to `/api/v1/health` check.
  - React + TypeScript frontend template initialized and builds.
  - PostgreSQL + pgvector Docker container starts.
  - Unit tests run with mocks and pass.
- **Phase 2 Acceptance (Current)**:
  - Document storage abstraction created (local files stored in `data/uploads/` at root).
  - Pydantic configuration settings loaded (embedding provider, dimensions).
  - Document parsing pipeline supports PDF, DOCX, XLSX, TXT formats.
  - Legacy `.xls` is explicitly unsupported and raises a clear `UnsupportedFileError`.
  - Database schema includes `Document` (with ingestion status and SHA-256 duplicate checks) and `DocumentChunk` with `pgvector` embeddings.
  - Transactions ensure all-or-nothing database entries on upload failures.
  - Embedding Service abstraction supports real and `mock` provider implementations.
  - Search endpoint provides top-k chunks with filename, page numbers, sections, text, and cosine similarity score.
  - Tests run with Docker Postgres + pgvector for integration checks, and use mocks for unit tests (no paid API required).
- **Phase 3 Acceptance (Completed)**:
  - Structured Evidence and Citations models defined.
  - MockLLMService and abstract LLM layers written.
  - Deterministic conflict detector and citation validator services completed.
  - Grounded question-answering with safety delimiter prompt injection protection.
  - Automated tests pass.
- **Phase 4 Acceptance (Completed)**:
  - Stateful LangGraph StateGraph workflow implemented.
  - Node transitions logged with execution durations.
  - Deterministic query analysis, evidence sufficiency routing, and conflict-aware answer drafting nodes.
  - Quality Gate and Human Review nodes verify state and flag review requirements.
  - Robust failure route handling database or LLM errors.
  - All 33 pytest tests pass successfully.
- **Phase 5 Acceptance (Completed)**:
  - Durable PostgreSQL checkpoint persistence implemented using custom `SQLAlchemyCheckpointer`.
  - Database schemas created for dossiers, findings, checkpoints, and execution history.
  - REST endpoints added for batch dossiers, sequential execution, and reviewer actions.
  - Independent finding execution isolation and run retry history trails enabled.
  - Verified and passed all persistent checkpointer tests.
- **Phase 6 Acceptance (Completed)**:
  - React + TypeScript dashboard UI developed and integrated.
  - Overall dossiers metrics (Total, Running, Completed, Review, Failed) visualised on the dashboard.
  - Dynamic page switching (Dashboard, Create Dossier, Dossier Details, Finding Review, Data Room).
  - Question list builder and batch run execution controls.
  - Interactive Human Review actions: Approve, Edit (overwriting answer/reasoning only), and Reject (with text reason).
  - Prominent Orange Conflict Warning and side-by-side comparative column UI (supporting vs contradicting evidence) for conflicting findings.
  - Citation explorer detailing reference file, page, section, and text excerpt.
  - Dynamic workflow progress path component visualising stage pipelines.
  - Data room manager for file listings, uploads, and cascade deletions.
  - Clean client-side TypeScript compilation (`npm run build` exits with code 0).
