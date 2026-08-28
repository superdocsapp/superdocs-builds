# Agentic Document Intelligence — Microfinance Compliance

An end-to-end pipeline that ingests a "pile" of financial documents, extracts structured facts with source provenance, evaluates compliance rules, and surfaces findings for human approval — with full checkpointed resumability and concurrent-run isolation.

---

## Quick Start (one command)

Prerequisites: **Docker**, **Docker Compose v2**, and [**uv**](https://docs.astral.sh/uv/getting-started/installation/) (Python package manager).

```bash
make demo
```

This single command:

1. Builds and starts PostgreSQL 16 + pgvector and the FastAPI service (`docker compose up`)
2. Applies all 15 database migrations (schema, tables, triggers, indexes)
3. Generates a deterministic 5-document synthetic pile and seeds it into the database

After it completes:

| Service    | URL                              |
|------------|----------------------------------|
| API        | http://localhost:8000/health      |
| PostgreSQL | `localhost:5432` (postgres/postgres/docdb) |

To bring everything down: `make down` (or `make clean` to also wipe the volume).

---

## Supported Document Formats

| Format | MIME Type | Notes |
|--------|-----------|-------|
| **PDF** | `application/pdf` | Text-layer extraction via pdfplumber; scanned PDFs not yet supported |
| **DOCX** | `application/vnd.openxmlformats-officedocument.wordprocessingml.document` | Standard Office Open XML |
| **Plain text** | `text/plain` | Direct ingestion, no conversion step |

The pipeline determines format at the `ingest` node via MIME detection. Adding support for a new format requires only a new text-extraction adapter in `src/pipeline/nodes/extract_text.py` — no graph changes.

---

## Domain

**Microfinance and consumer loan compliance** (Financial Compliance & Credit Auditing).

The system is purpose-built for document piles containing:

- Loan agreements (principal, rate, tenure, fees, penal clauses)
- Modification agreements (rate reductions, moratoriums, term changes)
- Repayment statements (tabular or narrative payment histories)

Documents are organized into **piles** — the unit of work handed to a run (`POST /piles`, upload documents via `POST /piles/{id}/documents`). A run is started against one pile and one playbook; the pile's document list is read at run-start and treated as immutable for that run's duration.

Compliance rules live in YAML playbooks under `rules/`. The shipped playbook (`microfinance_v1`) checks:

| Rule | Description |
|------|-------------|
| MF-001 | APR must not exceed 36% |
| MF-002 | Processing fee must be disclosed |
| MF-003 | Interest rate must match latest modification |
| MF-004 | Late payment penalty must not exceed 5% of outstanding |

A second evaluation with different documents works without code changes — drop new files in the same declared formats (PDF, DOCX, or plain text) within the microfinance/consumer-loan domain, and the existing pipeline + rules apply as-is. To add domain-specific rules, edit or add YAML in `rules/` (no Python changes required).

---

## Architecture Decisions — What We Cut and Why

| Decision | What was cut / chosen | Why |
|----------|-------------|-----|
| **LangGraph topology, custom checkpoint runner** | `langgraph` is installed and `graph.py` compiles a real `StateGraph` (nodes + conditional edges), but API runs execute via `demo_executor.run_pipeline`, which drives nodes sequentially with Postgres-backed per-node checkpoints — the same semantics LangGraph's checkpointer provides | Keeps graph topology portable to LangGraph's runtime while owning the durability contract directly; kill-and-resume is enforced by property tests rather than delegated |
| **Real LLM calls (DeepSeek), protocol-gated** | Extraction, classification, rule evaluation, and confidence scoring call DeepSeek via an OpenAI-compatible client (`src/llm/deepseek_client.py`) when `DEEPSEEK_API_KEY` is set; tests inject mock `LLMClient` implementations through protocols | Avoids API-key gating for evaluators in CI; production wiring is an env var, not a code change. SSE streaming broadcasts node progress live (`GET /runs/{id}/stream`) |
| **Hybrid extraction: structured-first, LLM fallback per field** | Type-specific structured extractors run first; any field returning `not_found` is re-extracted by the LLM; unregistered document types go straight to LLM-only extraction. Each claim records `_extraction_method` (`structured`, `llm_fallback`, or `llm`) | Regex alone collapsed from 100% template coverage to 17% on paraphrased documents (see DECISIONS.md); hybrid keeps deterministic speed where phrasing is fixed and LLM reach everywhere else. Resolves the 2026-08-12 PENDING decision |
| **Verbatim-quote citation strategy for LLM facts** | The LLM returns a verbatim quoted span per field; exact string match locates it in source text to compute offsets (normalized fallback); failure marks the claim `citation_status: unverifiable` with zeroed span | Guarantees every extracted fact is either anchored to exact character offsets or explicitly flagged — never silently unanchored |
| **Embedding node implemented, provider unwired** | The `embed` node is fully implemented (atomic batch embed → pgvector store) behind `EmbeddingService`/`VectorStore` protocols, but no default provider is configured — without injected services the node returns a transient error | pgvector schema ready; concrete provider adds cost/API-key coupling — wire via config switch when needed |
| **No scanned-PDF OCR** | Only text-layer PDFs are supported | OCR adds Tesseract/cloud-vision dependencies and latency; the compliance domain primarily uses digitally-generated loan docs |
| **No React UI in Docker** | Frontend is a separate Vite dev server, not containerized | Keeps the backend image small and CI fast; the frontend is stateless and talks to the API over localhost |
| **No cloud deployment** | Docker Compose for local only | Scope is demo + evaluation; production would add Terraform/CDK, secrets management, and multi-region Postgres — all out of scope for this prototype |
| **No authentication** | API is unauthenticated | Prototype scope; production would add JWT/OAuth middleware |

---

## Project Structure

```
├── scripts/
│   └── seed_demo.py           # Generates + inserts the synthetic demo pile
├── rules/                     # YAML compliance playbooks (no code edits to add rules)
├── migrations/                # Sequential SQL migrations (001–015)
├── src/
│   ├── models/                # SQLAlchemy models (13 tables)
│   ├── llm/
│   │   └── deepseek_client.py # OpenAI-compatible DeepSeek client (env-gated)
│   ├── pipeline/
│   │   ├── nodes/             # 13 async pipeline nodes
│   │   ├── extractors/        # Type-specific extractors + LLM extractor w/ citation strategy
│   │   ├── graph.py           # LangGraph StateGraph assembly (all nodes, conditional edges)
│   │   ├── demo_executor.py   # Real-run executor: LLM calls, SSE events, durability writes
│   │   ├── executor.py        # ResumableExecutor (checkpoint-based runner)
│   │   ├── stores.py          # SQL stores (run/resume/history/cost) + in-memory test store
│   │   ├── approval.py        # Approval service (in-memory) + approval_postgres.py (durable)
│   │   ├── incremental.py     # Incremental updates; contradictions → approval queue
│   │   ├── deliverable.py / deliverable_store.py  # Run deliverables (approved output)
│   │   ├── history*.py        # Change history: what changed, when, why
│   │   ├── source_linker.py   # Attaches fact spans → source_locations rows
│   │   ├── citation_payload.py# Grounded/unverifiable citation payloads
│   │   ├── piles_api.py       # Pile CRUD + document upload
│   │   ├── upload_api.py      # File upload handling
│   │   ├── facts_api.py       # Claim/fact inspection endpoints
│   │   └── ...                # Config, routing, playbook, evaluators, polling, watcher
│   ├── mcp_server.py          # MCP server (8 tools, stdio transport)
│   └── main.py                # FastAPI entrypoint (runs, piles, approvals, cost, report, SSE)
├── tests/
│   ├── synthetic/             # Deterministic document generators
│   ├── microfinance/          # Domain generators + property tests (extraction, classifier…)
│   ├── pipeline/              # Unit + property-based pipeline tests
│   ├── test_schema/           # Schema correctness (requires Postgres)
│   ├── test_resumability.py   # Kill-and-resume invariant tests
│   ├── test_concurrency.py    # Run isolation tests
│   ├── test_paraphrased_extraction.py  # Template vs paraphrased coverage gap evidence
│   ├── test_prompt_injection_resistance.py  # Hostile document content hardening
│   └── test_mcp_integration.py # End-to-end via MCP tools
├── frontend/                  # React + Vite review interface (Vitest + Playwright e2e)
├── docker-compose.yml         # PostgreSQL 16 + pgvector, API service
├── Dockerfile                 # Python 3.11-slim, uv-based
├── Makefile                   # make demo = up + migrate + seed
└── pyproject.toml
```

---

## Running Tests

```bash
# All tests (no database needed for pipeline + invariant tests)
make test

# Schema tests (requires running Postgres — run 'make up' first)
make test-schema
```

---

## MCP Server

The system is also available as an MCP server (stdio transport) exposing the same operations as the REST API through 8 tools: `start_run`, `get_run_status`, `list_pending_approvals`, `decide_approval`, `get_deliverable`, `get_change_history`, `get_run_cost`, `cancel_run`.

```bash
uv run python -m src.mcp_server
```

---

## Makefile Targets

| Target | Description |
|--------|-------------|
| `make demo` | **The one command** — up + migrate + seed |
| `make up` | Start containers |
| `make down` | Stop containers |
| `make clean` | Stop + wipe volumes |
| `make migrate` | Apply SQL migrations |
| `make seed` | Insert synthetic demo pile |
| `make test` | Run test suite |
| `make frontend` | Start Vite dev server |
