# Sprint-Based Dev Plan: Documentation Drift Detector

*SuperDocs-backed, 4-agent git-worktree architecture, weekend-viable.*

---

## 0. Architecture Overview

```
                         git worktrees (main + 4)
                              │
              ┌───────────────┼───────────────┐
              │               │               │
         Agent #1         Agent #2         Agent #3         Agent #4
      (File Ingestor)  (Analysis Core)   (Edit Engine)   (Frontend UI)
              │               │               │               │
              ▼               ▼               ▼               ▼
        SuperDocs MCP    Postgres/pgvector  SuperDocs MCP    React (Vite)
        upload/get_chunks  Finder/Verifier   chat_async/     review-gate
                           /Judge(spawn)     approve/export  /cost-panel
              │               │               │               │
              └───────────────┴───────────────┘               │
                      shared modules:                          │
              models.py, db.py, trace.py,                      │
              LLMProvider, SuperDocsClient               │
```

**Why git worktrees:** Each agent owns a dedicated working directory checked out from the same repo. They share `.git` history but never collide on uncommitted state. `main` holds the shared library core; each agent branch stays isolated. Integration happens via `main` merges and the shared Postgres database.

**Inter-agent communication:** A lightweight FastAPI event bus (`POST /events`) or, simpler: each agent polls a `jobs` table in Postgres. Agent #1 pushes an `ingestion_job` row; Agent #2 picks it up. Agent #3 pushes `edit_batch` rows; Agent #2's reviewer spawn polls for them. No message queue needed for a weekend build.

---

## 1. Shared Foundation (Sprint 0 — do first, before any agent)

This lives on `main`. Every agent imports from it.

### 1.1 Project scaffold
```
drift-detector/
├── shared/
│   ├── __init__.py
│   ├── models.py          # Pydantic models: Document, Chunk, ChangeFact, Finding, etc.
│   ├── db.py              # SQLAlchemy + pgvector setup, all tables from §7
│   ├── trace.py           # append-only TraceLogger
│   ├── llm_provider.py    # LLMProvider interface + AzureOpenAI impl + mock
│   ├── superdocs_client.py# SuperDocsClient — wraps the MCP tools
│   └── config.py          # env vars, database URL, API keys
├── tests/
│   ├── fixtures/          # seeded corpus md/html files
│   ├── test_llm_mock.py
│   ├── test_superdocs_mock.py
│   └── test_pipeline.py   # §12 behaviors
├── migrations/
│   └── 001_init.sql       # full schema
├── frontend/              # Agent #4 workspace (React Vite)
├── agent_ingestor/        # Agent #1 workspace (git worktree)
├── agent_analyzer/        # Agent #2 workspace (git worktree)
├── agent_editor/          # Agent #3 workspace (git worktree)
├── pyproject.toml / requirements.txt
├── docker-compose.yml     # Postgres + pgvector
└── README.md
```

### 1.2 `SuperDocsClient` — the MCP wrapper (critical)

All 4 agents hit SuperDocs through this one module. It wraps the MCP tools as async Python methods:

```python
class SuperDocsClient:
    session_id: str          # sticky, reused
    # INGEST
    async def upload_document(file_path: str) -> ParsedDocument
        # calls upload_document_base64 → returns chunked HTML + chunk_ids
    async def get_document_detail(doc_id: str) -> DocumentDetail
    # EDIT
    async def chat_async(message: str, approval_mode: str, model_tier: str) -> JobId
    async def get_job(job_id: str) -> JobResult
    async def approve_change(job_id, change_id, approved, feedback) -> ...
    # EXPORT
    async def request_download_url(format: str) -> ExportResult
```

Every call emits a trace record with `superdocs_ops` counted.

### 1.3 `LLMProvider` interface

```python
class LLMProvider(ABC):
    async def complete(prompt: str, schema: Type[BaseModel]) -> T
    async def embed(text: str) -> list[float]
```

Azure OpenAI impl + `MockLLMProvider` for tests. The mock replays fixtures from JSON files; every test in §12 runs with the mock, zero live keys.

### 1.4 Database (Postgres + pgvector)

`docker-compose.yml` brings up Postgres with the pgvector extension. Run `001_init.sql` once. Every table from §7, plus a `jobs` table for inter-agent dispatch:

```sql
CREATE TABLE jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    kind TEXT NOT NULL,            -- ingestion | analyze | edit_batch
    status TEXT DEFAULT 'pending', -- pending | claimed | completed | failed
    agent TEXT NOT NULL,           -- agent_1 | agent_2 | agent_3
    payload JSONB,
    result JSONB,
    claimed_by TEXT,
    claimed_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now()
);
```

### 1.5 Acceptance criteria for Sprint 0
- [ ] `docker-compose up` → Postgres + pgvector running
- [ ] `001_init.sql` creates all tables
- [ ] `SuperDocsClient` connects to SuperDocs MCP and returns `session_id`
- [ ] `LLPProvider` (mock) emits structured JSON matching Pydantic schemas
- [ ] One integration smoke-test: upload a tiny .md → chunk_ids returned

---

## 2. Agent #1 — File Ingestor (Sprint 1)

**Responsibility:** Watch the `watched/` directory, detect changed files via hash-diff, upload them through SuperDocs, store chunked HTML + `chunk_id → content_hash` map in Postgres, emit `ingestion_job` rows for Agent #2.

### 2.1 What it does

```
watched/ ──► hash-diff (sha256) ──► changed files only
                                          │
                    ┌─────────────────────┘
                    ▼
            SuperDocs.upload_document_base64(file)
                    │
                    ▼
            SuperDocs returns chunked HTML with data-chunk-id
                    │
                    ▼
            Parse chunks → INSERT INTO documents, chunks
            (file_hash as idempotency key — duplicate = no-op)
                    │
                    ▼
            INSERT INTO jobs (kind='ingestion', payload={document_ids, run_id})
```

### 2.2 Files to create (in `agent_ingestor/` worktree)

| File | Purpose |
|------|---------|
| `watcher.py` | `watchdog`-based directory monitor, hash-diff on change events |
| `ingestor.py` | calls `SuperDocsClient.upload_document`, parses chunks, inserts DB rows |
| `dispatcher.py` | inserts `jobs` row to wake Agent #2 |
| `main.py` | FastAPI entrypoint: `POST /watch` to start, `GET /status` |
| `cli.py` | `python -m agent_ingestor watch ./watched/ --run-id abc123` |

### 2.3 Key design decisions

- **Idempotency by file_hash:** `documents.file_hash` has a UNIQUE constraint. Second upload of the same file → detected in Python, skip SuperDocs call, return existing `document_id`.
- **Run scoping:** Every ingestion belongs to a `run_id`. The watcher emits one run per trigger (manual or file change).
- **Polling vs. push:** `watchdog` fires on `FileSystemEventHandler.on_modified`. Debounce 2 seconds to avoid double-fires on atomic writes.

### 2.4 Acceptance criteria
- [ ] Drop a `.md` file into `watched/` → chunks appear in `documents` + `chunks` tables with correct `data-chunk-id`s
- [ ] Drop the same file again → no-op (idempotency hit)
- [ ] Hash-diff: modify 1 of 3 docs → only the changed one re-uploads
- [ ] `jobs` row appears with `kind='ingestion'` and `status='pending'`

---

## 3. Agent #2 — Analysis Core (Sprint 2)

**Responsibility:** Poll `jobs` for `kind='ingestion'`, run the EMBED → PARSE_CHANGES → RETRIEVE → FINDER → VERIFIER → PROPOSE_FIX → JUDGE(semantic) pipeline. Emit `review_batch` rows for the human gate and `edit_batch` jobs for Agent #3. Spawn the REVIEW flow.

### 3.1 What it does

```
jobs (ingestion) ──► claim row → lock
                          │
          ┌───────────────┼───────────────┐
          ▼               ▼               ▼
      EMBED          PARSE_CHANGES     RETRIEVE
  (pgvector,        (light LLM →        (hybrid
   content_hash      change_facts)      vector+kwd)
   cache hit)
          │               │               │
          └───────────────┼───────────────┘
                          ▼
                       FINDER (LLM)
                    ┌── confirm/abstain
                    │      │
                    │      ▼
                    │  VERIFIER (LLM, fresh ctx)
                    │      │
                    │      ▼
                    │  PROPOSE_FIX (code for literals, LLM for rewrites)
                    │      │
                    │      ▼
                    │  JUDGE semantic (LLM)
                    │      │
                    │      ▼
                    │  [ CONFIRMED_DRIFT | NO_DRIFT | UNKNOWN ]
                    │
                    └──► INSERT INTO findings
                         INSERT INTO jobs (kind='review_batch', payload={finding_ids})
```

### 3.2 Files to create (in `agent_analyzer/` worktree)

| File | Purpose |
|------|---------|
| `poller.py` | polls `jobs` table, claims rows, orchestrates the pipeline |
| `embedder.py` | calls `LLMProvider.embed()`, checks `content_hash` cache, inserts pgvector |
| `change_parser.py` | light LLM call → structured `change_facts[]` with Pydantic schema enforcement |
| `retriever.py` | hybrid: pgvector cosine + keyword match, top-K candidates per change_fact |
| `finder.py` | LLM prompt: `{chunk_html, change_fact} → finding_state + evidence` |
| `verifier.py` | independent LLM call: confirm evidence_quote in chunk, reject injection |
| `proposer.py` | literal substitutor (`npm`→`pnpm`) + constrained LLM for rewordings |
| `judge_semantic.py` | thin LLM: "does fix resolve drift without new claims?" |
| `dispatcher.py` | pushes `review_batch` and `edit_batch` jobs |
| `main.py` | FastAPI: `POST /analyze`, `GET /run/{run_id}/status`, `GET /findings/{run_id}` |
| `cli.py` | `python -m agent_analyzer run --run-id abc123` |

### 3.3 Key design decisions

- **FINDER authority:** It can abstain → UNKNOWN. Verifier can bounce with feedback → back to Finder once, then UNKNOWN.
- **Schema-forced evidence:** `CONFIRMED_DRIFT` MUST have `evidence_chunk_id + evidence_quote + change_fact_id`. Validation is in code, not a prompt. Invalid output → schema fail → UNKNOWN (with one repair attempt).
- **Checkpointed:** Each pipeline node writes to `run_steps` with `input_hash`. Resume replays only incomplete nodes. This is how `kill -9` mid-run recovers.
- **Stopping rule:** If budget exceeded, stop after current node, report partial.
- **Decoy handling:** `PARSE_CHANGES` emits all change_facts. RETRIEVE returns 0 candidates for a decoy → Finder never called → no false positive.

### 3.4 Acceptance criteria
- [ ] Run on a 3-doc corpus with 2 injected drifts → FINDER finds both, one abstention on a tricky section
- [ ] VERIFIER bounces a bad finding → Finder re-tries, then falls to UNKNOWN
- [ ] Clean corpus (decoys only) → zero CONFIRMED findings
- [ ] Kill after FINDER, resume → no duplicated findings, pipeline continues from VERIFIER
- [ ] UNKNOWN queue separate from FAILED queue: UNKNOWN items never retried, FAILED items retried 3× with backoff

---

## 4. Agent #3 — Edit Engine (Sprint 3)

**Responsibility:** Poll `jobs` for `kind='edit_batch'`, execute the two-phase apply protocol (§5 of the spec). Spawn the JUDGE(byte) — which is **code, not an LLM**. Apply approved fixes through SuperDocs, prove byte-identity of untouched chunks, export the final doc. Also hosts the REVIEW REST endpoint (human gate) that the frontend calls.

### 4.1 What it does

```
jobs (edit_batch) ──► claim row
                          │
          ┌───────────────┼───────────────┐
          │               │               │
    REVIEW (human)    APPLY           JUDGE byte
   (Agent #4 calls    (SuperDocs       Phase A+B
    this REST API)     chat_async)     (CODE only)
          │               │               │
          ▼               ▼               ▼
   Per-item approve  chat_async(        snapshot hash
   or reject with    scoped edit,       → approve if
   feedback          ask_every_time)    target chunks ok
                     → poll job         → re-fetch
                     → Phase A          → assert all
                     → approve          non-target
                     → Phase B          chunks unchanged
                     → commit
```

### 4.2 Files to create (in `agent_editor/` worktree)

| File | Purpose |
|------|---------|
| `review_api.py` | FastAPI routes: `GET /review/{run_id}`, `POST /review/{finding_id}/approve`, `POST /review/{finding_id}/reject` |
| `editor.py` | orchestrates the apply protocol: snapshot → chat_async → approve → re-snapshot → assert |
| `judge_byte.py` | **PURE CODE**: Phase A (chunk_id subset check), Phase B (non-target byte-identity assertion). Zero LLM calls. |
| `exporter.py` | calls `SuperDocsClient.request_download_url` → returns signed URL |
| `dispatcher.py` | polls `edit_batch` jobs, marks them as claimed |
| `main.py` | FastAPI: review endpoints + `POST /apply/{run_id}` |
| `cli.py` | `python -m agent_editor apply --run-id abc123` |

### 4.3 Key design decisions

- **The two-phase protocol (spec §5) is non-negotiable:**
  - Phase A: Before approving, assert `change.chunk_id ⊆ intended_target_ids`. Fail → reject batch, `NEEDS_ESCALATION`.
  - Phase B: After applying, re-fetch doc, assert `post[id] == snapshot[id]` for all non-target chunks. Fail → ALARM, revert, commit blocked.
  - Both are hash comparisons. LLM never enters.
- **Scoped edits only:** The instruction to SuperDocs is always `"In chunk {id}, replace '{old}' with '{new}'"`. Never wider.
- **Review is persistent:** `review_decisions` table stores per-item decisions. Survive reload. Human can reject one item without discarding the rest.
- **Export is free:** SuperDocs exports don't count as operations. Export after every successful apply batch.

### 4.4 Acceptance criteria
- [ ] Single edit (`npm`→`pnpm`) flows through: snapshot → chat_async → approve → re-snapshot → byte-identity passes
- [ ] Edit targeting wrong chunk → Phase A rejects, nothing applied
- [ ] Post-edit chunk corruption → Phase B alarms, revert triggers
- [ ] Two findings, human approves one and rejects other → approved one applied, rejected one in `review_decisions` with feedback
- [ ] `POST /export/{run_id}` → returns signed download URL

---

## 5. Agent #4 — Frontend UI (Sprint 4)

**Responsibility:** React (Vite) app that polls Agent #2's findings API and Agent #3's review API. Renders the review gate, UNKNOWN panel, FAILED panel, cost panel, and per-finding before/after diffs. This is the "hero shot" for the demo.

### 5.1 What it shows

```
┌─────────────────────────────────────────────────────┐
│  Drift Detector — Run #abc123        [Cost: 12 ops] │
├─────────────────────────────────────────────────────┤
│  ┌─ Findings (3) ─────────────────────────────────┐ │
│  │ [CONFIRMED_DRIFT] doc/intro.md, chunk c42       │ │
│  │   Before: "Run npm install..."                  │ │
│  │   After:  "Run pnpm install..."                 │ │
│  │   Evidence: "Release v2.0: npm renamed to pnpm" │ │
│  │   [Approve] [Reject] [Reject with feedback...]  │ │
│  ├─────────────────────────────────────────────────┤ │
│  │ [CONFIRMED_DRIFT] doc/config.md, chunk c78      │ │
│  │   ...                                           │ │
│  ├─────────────────────────────────────────────────┤ │
│  │ [UNKNOWN] doc/old-ref.md, chunk c99             │ │
│  │   Reason: "Cannot parse section structure"      │ │
│  │   [Mark reviewed]                               │ │
│  └─────────────────────────────────────────────────┘ │
│  ┌─ Unknown panel (2) ────────────────────────────┐ │
│  │ ... (verify manually list)                      │ │
│  └─────────────────────────────────────────────────┘ │
│  ┌─ Failed panel (1) ─────────────────────────────┐ │
│  │ ... (retry/escalate list)                       │ │
│  └─────────────────────────────────────────────────┘ │
│  ┌─ Cost panel ───────────────────────────────────┐ │
│  │ Embed: 3 ops, Finder: 5 ops, Verifier: 2 ops   │ │
│  │ Apply: 2 ops. Total: 12 ops.                   │ │
│  └─────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────┘
```

### 5.2 Files to create (in `frontend/` worktree)

| File | Purpose |
|------|---------|
| `src/App.tsx` | top-level layout, route wiring |
| `src/api.ts` | fetch wrappers for Agent #2 + Agent #3 REST endpoints |
| `src/components/FindingsList.tsx` | grouped by document, per-finding card |
| `src/components/FindingCard.tsx` | before/after diff, evidence quote, approve/reject buttons |
| `src/components/UnknownPanel.tsx` | UNKNOWN findings list with "mark reviewed" |
| `src/components/FailedPanel.tsx` | FAILED items with retry button + error reason |
| `src/components/CostPanel.tsx` | ops/tokens breakdown sourced from trace |
| `src/components/DiffView.tsx` | simple inline diff (can evolve to Cursor-style later) |

### 5.3 Key design decisions

- **Polling, not WebSocket.** `setInterval(fetch, 3000)` is fine for a weekend build. The run is sequential anyway; the frontend just reflects state.
- **Per-item independence:** Each approve/reject is a `POST` to Agent #3. One rejection doesn't block others.
- **Cost sourced from trace:** `GET /run/{run_id}/cost` on Agent #2 aggregates the `trace` table. No parallel artifact.
- **Start with side-by-side card view.** Cursor-style inline decoration is depth work (spec §9 allows it).

### 5.4 Acceptance criteria
- [ ] Page loads → fetches findings from Agent #2 → renders list with documents grouped
- [ ] Click "Approve" → POST to Agent #3 → finding status updates to `applied`
- [ ] Click "Reject with feedback" → text input → POST → `reviewed` with feedback saved
- [ ] UNKNOWN panel shows all UNKNOWN findings with reasons
- [ ] Cost panel shows per-stage ops breakdown, sourced from DB trace
- [ ] Zero findings → page shows "No drift detected" clean state

---

## 6. Integration & Delivery (Sprint 5 — glue)

### 6.1 What ties it together
- [ ] `docker-compose up` brings Postgres + pgvector + all 4 agent FastAPI servers
- [ ] One `POST /run` to Agent #1 starts the full pipeline end-to-end
- [ ] Agent #1 → jobs table → Agent #2 picks up → emits review_batch → Agent #4 shows it → human approves → Agent #3 edits → exports
- [ ] Run the §12 tests with mock LLM + mock SuperDocs: all 7 behaviors pass
- [ ] Run on the seeded corpus with real SuperDocs + Azure LLM → emit metrics (precision, recall, UNKNOWN rate, byte-identity 100%)
- [ ] README with setup instructions, one-command demo run

### 6.2 Git worktree setup

```bash
# On main branch (shared core)
git checkout -b main

# Create worktrees for each agent
git worktree add ../agent_ingestor agent_1
git worktree add ../agent_analyzer  agent_2
git worktree add ../agent_editor    agent_3
git worktree add ../frontend        agent_4

# Each worktree has its own venv / node_modules
# Shared: .git, docker-compose.yml, migrations/
# Each branch diverges independently; merge back to main for integration
```

### 6.3 Inter-agent contract (the `jobs` table is the API)

| From | To | Job `kind` | Payload | Consumed by |
|------|----|-----------|---------|-------------|
| Agent #1 | Agent #2 | `ingestion` | `{run_id, document_ids[]}` | Agent #2 poller |
| Agent #2 | Agent #3 + #4 | `review_batch` | `{run_id, finding_ids[]}` | Agent #4 reads it; Agent #3 waits for approvals |
| Frontend | Agent #3 | (REST call) | `POST /review/{id}/approve` | Agent #3 review_api |
| Agent #3 | (self) | `edit_batch` | `{run_id, approved_finding_ids[]}` | Agent #3 dispatcher |

---

## 7. Risk Register

| Risk | Mitigation |
|------|-----------|
| SuperDocs session timeout | `SuperDocsClient` auto-refreshes; session_id persisted in DB |
| LLM costs spiral | Stopping rule in RETRIEVE (§6 spec): cap candidates per change_fact; per-run budget in config |
| pgvector setup fails | Fallback to exact-match keyword retriever (worse recall, but pipeline still runs) |
| Agent #2 blocks Agent #3 | Review is the human gate — Agent #3 only acts on approved items. No deadlock risk |
| Concurrent runs on same SuperDocs doc | Postgres advisory lock per `superdocs_doc_id`; serialize |
| MCP tool latency | `SuperDocsClient` wraps with retry + timeout; timeout → FAILED queue |

---

## 8. Order of Execution (by Sprint)

| Sprint | What | Output |
|--------|------|--------|
| **0** | Shared foundation (models, DB, SuperDocsClient mock, LLMProvider mock) | Working `docker-compose`, DB tables, one smoke test |
| **1** | Agent #1 — File Ingestor | `watched/` → SuperDocs → chunks in DB → jobs row |
| **2** | Agent #2 — Analysis Core | EMBED → FIND → VERIFY → PROPOSE → findings in DB |
| **3** | Agent #3 — Edit Engine | Two-phase apply, review REST API, export |
| **4** | Agent #4 — Frontend | React review gate with all 4 panels |
| **5** | Integration + tests | End-to-end on seeded corpus, metrics, README |