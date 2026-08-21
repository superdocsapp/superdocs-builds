# Documentation Drift Detector

Built on SuperDocs by **Gabiro Arnaud**.

SuperDocs-backed multi-agent pipeline that detects, proves, and fixes documentation drift against a change feed.

## What it does

Documentation goes stale silently. A port default changes, a command is
renamed, a flag is deprecated — and the docs keep confidently describing the
old behaviour until someone is burned by them.

This tool takes a **documentation set** and a **change feed** (release notes,
changed defaults, renamed commands) and finds every section that is now wrong.
For each one it must cite the chunk and quote the evidence, or it is not
allowed to claim drift at all. It proposes a scoped fix, a human approves or
rejects item by item, and the approved edit is applied **through SuperDocs** to
that one chunk — with a proof that no other chunk changed by a single byte.

Where it cannot verify something, it says `UNKNOWN` rather than guessing. Every
step is written to an append-only trace, so a run can be audited after the fact
rather than taken on faith.

## What SuperDocs features it uses

| SuperDocs capability | Endpoint | What this build does with it |
|---|---|---|
| **Document parsing into addressable chunks** | `POST /v1/documents/upload-base64` (`return_html=true`) | The whole precision guarantee. Every paragraph, heading and table cell comes back carrying a `data-chunk-id`; those ids are the addressing scheme for every later edit. |
| **Multi-document sessions** | `POST /v1/sessions/{id}/documents/open`, `.../focus`, `GET /v1/sessions/{id}/documents` | Each document is ingested into its own session and re-opened and focused before it is edited. The session roster is also how the durable document id is resolved. |
| **Chat editing with approval gating** | `POST /v1/chat/async` (`approval_mode=ask_every_time`, `model_tier=max`), `POST /v1/chat/{id}/approve`, `POST /v1/chat/{id}/continue` | Applies one approved fix as a scoped instruction naming a single chunk. Proposed changes are inspected and can be *denied* before anything is committed. |
| **Job polling** | `GET /v1/jobs/{job_id}` | Drives the apply protocol: wait for `awaiting_approval`, branch on `metadata.awaiting_kind`, then settle. |
| **Document read-back** | `GET /v1/documents/{id}?include_html=true` | The byte-identity proof. Chunk hashes before and after an edit are compared to show nothing outside the target chunk moved. |
| **Export** | `POST /v1/downloads` | Signed download URL for the corrected document after an apply. |

Two things are deliberately **not** done through SuperDocs — in-document search
and the one-session-per-document ingestion model. Both are explained in
[Caveats](#caveats-and-honest-limits).

## Repository Layout

```
Documentation drift detector/
├── backend/                     # Python backend
│   ├── src/
│   │   ├── core/                # shared foundation: models, DB, LLMProvider, SuperDocsClient, trace
│   │   └── agents/
│   │       ├── ingestor/        # watch/upload/chunk-id management (Agent #1)
│   │       ├── analyzer/        # EMBED/FINDER/VERIFIER/JUDGE pipeline (Agent #2)
│   │       └── editor/          # two-phase byte Judge + review API (Agent #3)
│   ├── tests/
│   │   ├── core/                # tests for src/core
│   │   ├── ingestor/            # tests for agents/ingestor
│   │   ├── analyzer/            # tests for agents/analyzer
│   │   ├── editor/               # tests for agents/editor
│   │   └── fixtures/corpus/     # seeded corpus (intro.md, config.md, clean.md, change_feed.jsonl)
│   ├── migrations/
│   │   ├── 001_init.sql         # full Postgres + pgvector schema
│   │   └── 002-004_*.sql        # edit history, search text, chunk order
│   ├── config/
│   │   ├── docker-compose.yml   # Postgres + pgvector service
│   │   └── .env.template        # SuperDocs + Anthropic Foundry / Azure config
│   ├── conftest.py               # adds src/ to sys.path for tests
│   ├── pyproject.toml
│   └── requirements.txt
├── frontend/                     # React (Vite + TS) review UI (Agent #4)
│   ├── src/
│   │   ├── components/          # Layout, FindingCard, DriftDiffPanel, ToastStack, ...
│   │   ├── pages/                # ReviewPage, DocumentsPage
│   │   ├── runs/RunContext.tsx   # shared "selected run" state across pages
│   │   ├── notifications/        # toast notification system
│   │   ├── api.ts                # reads VITE_INGESTOR/ANALYZER/EDITOR_API_URL
│   │   ├── App.tsx               # router root (react-router-dom)
│   │   ├── index.css             # gray sidebar + white panel design system, sharp edges
│   │   └── main.tsx
│   ├── .env.example              # backend API base URLs (copy to .env)
│   ├── index.html
│   ├── package.json
│   ├── tsconfig.json
│   └── vite.config.ts
├── Sprint-based-dev-plan.md
└── README.md
```

## Architecture

```
              backend/src/agents
        ┌───────────┼───────────────┐
        ▼           ▼               ▼
    ingestor     analyzer         editor            frontend/
  (watch/upload  (FINDER/VERIFY/  (2-phase byte    (React review
   chunk-ids)     PROPOSE/JUDGE)   Judge, review    gate + cost
                                    API)             panel)
        │           │               │                  │
        └───────────┴───────────────┴──────────────────┘
                     backend/src/core (shared)
           models · db · trace · LLMProvider · SuperDocsClient
```

## Quick Start

```bash
# 1. Start Postgres + pgvector
docker compose -f backend/config/docker-compose.yml up -d
# (waits for health check, runs backend/migrations/001_init.sql)

# 2. Copy and configure env
cp backend/config/.env.template backend/config/.env
# Edit backend/config/.env with your SUPERDOCS_API_KEY and ANTHROPIC_API_KEY

# 3. Create a venv and install Python deps
cd backend
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt   # Windows
# .venv/bin/python -m pip install -r requirements.txt          # macOS/Linux

# 4. Run all tests (no live keys needed — mocks only)
.venv/Scripts/python.exe -m pytest tests/ -v

# 5. Start each agent (separate terminals, from backend/).
# Invoke uvicorn via the venv's python directly — no "activate" needed,
# and this avoids PATH issues if your shell's default `python` isn't the
# one the venv/deps were installed into.
# Terminal 1 — Ingestor API, port 8001
.venv/Scripts/python.exe -m uvicorn agents.ingestor.main:app --app-dir src --port 8001

# Terminal 2 — Analyzer API, port 8002
.venv/Scripts/python.exe -m uvicorn agents.analyzer.main:app --app-dir src --port 8002

# Terminal 3 — Editor / Review API, port 8003
.venv/Scripts/python.exe -m uvicorn agents.editor.review_api:app --app-dir src --port 8003

# Terminal 4 — Frontend, port 3001
cd frontend
cp .env.example .env   # defaults already point to localhost:8001-8003
npm install && npm run dev

# 6. Demo run:
# Drop a .md file into watched/
curl -X POST http://localhost:8001/run -H "Content-Type: application/json" \
  -d '{"files": ["backend/tests/fixtures/corpus/intro.md"]}'
# Paste the returned run_id into the frontend at http://localhost:3001
```

## Frontend Pages

- **Global search** (sidebar, or `Ctrl`/`Cmd`+`K`) — searches every document in
  every run. Chunks containing the typed word are listed first with the match
  highlighted; chunks that are only related by meaning appear below, labelled
  as such. Selecting a result opens the document viewer scrolled to that exact
  section. Calls the Analyzer API (`GET /search`).

  **This is in-document semantic search, which SuperDocs does not natively
  provide.** SuperDocs *does* have semantic retrieval, but only over
  **attachments**: files uploaded via `/v1/attachments/upload-base64` are
  chunked, indexed and made "AI-searchable" so the model can reference them
  during a chat turn. That is deliberately distinct from the editable working
  document — the API describes attachments as "read-only context for the AI to
  reference, not the editable working document" — and it is not exposed as a
  query endpoint: the attachment routes are upload, status and delete only, so
  a client cannot ask for ranked hits and get back addressable chunks.

  Searching the documents themselves therefore had to be built here, on the
  pgvector index (`chunks.embedding`) already maintained for drift detection,
  over the `chunks.text_content` projection so queries match document text
  rather than HTML tag names. Literal and semantic hits are scored in disjoint
  bands, so a similarity score can never rank a chunk that lacks the word above
  one that contains it. If no embedding provider is configured, the literal
  half still works and the UI says why the other half is missing.
- **Documents** (`/documents`) — upload files (creates a new run, or appends to the
  selected one), delete documents, and open a document in-app to read its
  current text and its **edit history**: every applied fix with before/after
  content, the reviewer's note, and any approved fix that was blocked or failed.
  Calls the Ingestor API (`POST /upload`, `GET /documents`, `GET /documents/{id}`,
  `GET /documents/{id}/history`, `GET /documents/{id}/content`,
  `POST /documents/{id}/reingest`, `DELETE /documents/{id}`).

  **One SuperDocs session per document.** A session holds a single active
  document, so uploading into a shared session *replaces* whatever it already
  held — verified against the live API. Each ingest therefore gets its own
  session (keyed by content hash, so a retry does not spawn a duplicate), and
  the durable id is read from that session's one-entry roster rather than
  guessed from the title. Documents ingested before this hold an id that names
  nothing; **Re-ingest** rebuilds them from the original file in `watched/`.
- **Review** (`/`) — findings list with inline approve/reject, plus a **Compare**
  button on each finding that opens a side-panel diff viewer
  (`DriftDiffPanel`) showing the source document with the *current* text
  highlighted on the left and the *suggested* text highlighted on the right —
  approve/reject can be done directly from the panel too. **Approving applies
  the fix**: the edit is scheduled immediately and runs in the background under
  the two-phase byte Judge, and each card reports what actually happened —
  `Applied to document`, `Blocked — document unchanged`, or `Apply failed`.
  Approval (what a human decided) and application (what happened to the
  document) are shown as the separate facts they are.
- **Notifications** — a top-right toast stack (`notifications/NotificationContext.tsx`,
  `components/ToastStack.tsx`) surfaces upload, delete, approve, and reject
  outcomes without blocking the page.

## Test Suite

| Layer | Tests | Count | Requires |
|-------|-------|-------|----------|
| `backend/tests/core/` | Shared foundation (models, mocks, text projection, migrations) | 78 | nothing |
| `backend/tests/ingestor/` | File Ingestor (watcher, session-per-document, chunk order) | 30 | nothing |
| `backend/tests/analyzer/` | Analysis Core (parser, finder, verifier, search) | 86 | nothing |
| `backend/tests/editor/` | Edit Engine (byte Judge, apply write-back, history, missing docs) | 52 | nothing |
| `frontend/` | Frontend (tsc --noEmit + vite build) | build check | node |

**All 246 Python tests pass with `MockLLMProvider` — no live API keys needed.**

Run from `backend/`:
```bash
.venv/Scripts/python.exe -m pytest tests/ -v
```

## Caveats and honest limits

### 1. In-document semantic search is ours; SuperDocs' is attachment-only

SuperDocs **does** have semantic retrieval — but it is scoped to
**attachments**. A file uploaded to `/v1/attachments/upload-base64` is
processed asynchronously, chunked, indexed and made "AI-searchable" so the
model can reference it during a chat turn ("rewrite section 3 to match the
style guide PDF I attached"). `GET /v1/attachments/status/{session_id}` even
reports the chunk count once it is queryable.

Two things it is not:

- **Not the working document.** The API draws the line explicitly: attachments
  are "read-only context for the AI to reference, **not the editable working
  document**". There is no equivalent index over the documents being edited.
- **Not a query endpoint.** The attachment routes are upload, status and
  delete. Retrieval happens *inside* a chat turn, so a client cannot ask for
  ranked hits and get back addressable chunks to render or link to.

So **in-document semantic search had to be built here**, on the pgvector index
this project already maintains for drift detection:

- **Text, not markup.** Chunks are stored as SuperDocs HTML. Matching the
  markup would make `class`, `href` or `p` hit every chunk that has a tag,
  while a phrase broken by an inline tag (`npm <code>install</code>`) would
  never match. A `chunks.text_content` projection is written on ingest.
- **Exact and semantic are scored in disjoint bands**, not blended. Someone who
  typed a word is looking for that word, so no similarity score — however
  high — can rank a chunk lacking the query above one containing it.
- **A similarity floor.** Cosine similarity always returns *something*; without
  a floor, a nonsense query fills the page with confident-looking results.
- **It degrades rather than breaks.** With no embedding provider configured the
  literal half still works and the UI says why the other half is absent.

Driving search through `chat_async` instead was rejected: an LLM job per query,
polled for seconds, billed as operations, and — like attachment retrieval —
unable to hand back addressable chunk hits.

**If SuperDocs extends its index to working documents and exposes a query
endpoint**, the honest move is to delete `agents/analyzer/search.py` and call
it. The interface it presents (`GET /search` returning ranked chunk hits) would
not have to change.

### 2. One document = one session, even though users see one workspace

A SuperDocs session holds a **single active document**. Uploading a second file
into a session that already has one does not add a tab — it *replaces* the
existing document. Verified against the live API: the upload created no new
document and instead bumped `updated_at` on the session's existing durable
document, overwriting its content.

This build originally used one sticky session for the whole corpus, and every
upload silently destroyed the document uploaded before it. The fix:

- Each document is ingested into **its own session**, keyed by content hash so
  a retry lands on the same session instead of spawning duplicates.
- The document's session is **stored alongside it**, because open, focus, chat
  and approve are all session-scoped. Editing through a shared session would
  target whichever document that session happens to hold.
- The durable id is read from **that session's one-entry roster**. It cannot be
  resolved by title: titles are the filename stem, several documents
  legitimately share one, and an overwritten document keeps its old title while
  holding new content.
- Uploads answering `persisted: false` (what the API returns when no session is
  accepted) are rejected rather than stored as a document with no id.

**The user-facing consequence:** the UI presents one workspace over many
documents, but underneath there is one SuperDocs session per document. Users
never see a session id. The cost is that a document ingested under the old
shared-session model holds an id that names nothing, which is why
**`POST /documents/{id}/reingest`** exists — reachable from both the Documents
page and directly from a stalled finding on the Review page. It rebuilds a
document from its original file into a fresh session, rather than from stored
chunks, because SuperDocs mints **new random chunk ids on every upload**. That
also means a re-ingest necessarily invalidates existing findings for that
document; they are cleared (the UI says so before you confirm), while
applied-edit history is kept.

If SuperDocs later supports several co-resident documents per session, the
per-document session id becomes a single field change in `SuperDocsClient`.

### 3. Other limits worth stating plainly

- **Chunk ids are not stable across uploads.** They are random UUIDs, so any
  re-upload breaks references to prior chunks. Findings are therefore scoped to
  the parse that produced them.
- **Chunk order is not recoverable retroactively.** SuperDocs returns chunks in
  document order but the ids do not sort, so order is captured as
  `chunks.ordinal` at ingest. Documents ingested before that column existed
  sort last and may render out of order until re-ingested.
- **Detection quality is measured, not asserted.** `GET /run/{id}/metrics`
  reports precision, recall, F1 and UNKNOWN rate against the seeded corpus.
  Partial detection counts as a false negative rather than being excused.
- **The byte-identity proof covers chunks, not formatting internals.** It
  asserts that every non-target chunk hashes identically before and after an
  edit. That is a measurement, not an LLM opinion — but it is a statement about
  chunk content, not about the exported file's binary equality.
- **Export is session-scoped.** `POST /v1/downloads` exports the session, so
  with one document per session an export is per document by construction.
- **Scale is untested beyond a small corpus.** The literal half of search does a
  sequential scan over `text_content`; correct, but no trigram or full-text
  index is warranted at this size yet.

## Key Design Decisions

- **Two-phase byte Judge**: Phase A (pre-commit) checks stray chunks; Phase B (post-apply) asserts byte-identity of untouched chunks. Pure code — no LLM calls. Lives in `backend/src/agents/editor/judge_byte.py`.
- **UNKNOWN ≠ FAILED**: UNKNOWN is a first-class output (abstentions); FAILED is a retryable error. Separate queues.
- **Schema-forced evidence**: CONFIRMED_DRIFT must carry `evidence_chunk_id + evidence_quote + change_fact_id`. Can't populate → can't emit → falls to UNKNOWN.
- **Idempotent ingestion by file_hash**: Duplicate uploads are no-ops.
- **Inter-agent communication via Postgres `jobs` table** — no message queue needed.
- **`backend/conftest.py`** puts `src/` on `sys.path` so `core` and `agents.*` import as top-level packages without an editable install.
- **Frontend talks to two backend APIs** (no single monolith): `VITE_ANALYZER_API_URL` (findings, cost) and `VITE_EDITOR_API_URL` (review, approve/reject, apply, export). Configured via `frontend/.env` (gitignored; copy from `frontend/.env.example`).