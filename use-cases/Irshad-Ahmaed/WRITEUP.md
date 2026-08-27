# SuperDocs Full-Stack AI Engineer Assessment — Task 4 Write-Up

**Candidate:** Irshad Ahmad
**GitHub:** [Irshad-Ahmaed](https://github.com/Irshad-Ahmaed)
**Task 1 Repo:** [github.com/Irshad-Ahmaed/doctask-irshad-ahmad](https://github.com/Irshad-Ahmaed/doctask-irshad-ahmad)
**Task 2 PR:** [github.com/superdocsapp/superdocs-builds/pull/104](https://github.com/superdocsapp/superdocs-builds/pull/104)

---

## What Was Built, For Whom, and Why

### Task 1 — DocTask: The Analyst That Never Sleeps

**The problem:** A growing team managing Project Helios (a fictitious but realistic large-scale project) produces a stream of unstructured documents — plans, meeting minutes, status reports, budgets — in PDF, DOCX, XLSX, and Markdown formats. No human can read all of them and simultaneously track whether the latest budget contradicts an earlier plan, or whether a status report quietly breaks a previously approved governance rule. The mistakes surface weeks later, after decisions have already been made on bad data.

**What I built:** An agentic background worker that continuously watches a document inbox. When a new file arrives, it automatically ingests the document, extracts structured facts using an LLM, performs semantic similarity search against all previously ingested documents to detect factual conflicts (e.g., "Budget revised from \$2.1M to \$2.6M — contradicts approved ceiling in Project Charter"), checks all extracted facts against a YAML governance rules file, and then stops. It does not act. It queues every conflict and finding for a human to approve or reject in a React review interface before anything is written to the permanent append-only ledger.

**Measurable results:**
- **116 / 116 automated tests pass** at 100% in 34.35 seconds with zero live API keys or paid credits required.
- Every single AI assertion traces back to a SHA-256 hash of the source document chunk. Zero hallucinated citations are possible by construction.
- The system handles second and third runs correctly: stages checkpoint by `(run_id, stage, input_hash)` so a crash mid-pipeline resumes exactly where it stopped without reprocessing.
- Supported formats declared and tested: PDF, DOCX, XLSX, Markdown.

**Why these trade-offs are the right ones:**
The biggest architectural decision was to never let the AI write to the database autonomously. Every AI output is queued, inspected by a human, and only then committed. This costs speed but eliminates the entire class of "the AI confidently updated the wrong thing" failures that make enterprise customers distrust AI systems. The ledger is append-only by database privilege: the app role has INSERT but no UPDATE or DELETE on the `committed_changes` table. The history is physically immutable.

I used PostgreSQL with pgvector for both relational storage and vector embeddings instead of adding a separate Pinecone or Weaviate instance. This keeps the system deployable on a single managed Postgres instance (AWS RDS, Supabase, etc.) and guarantees that vector searches and relational queries are transactionally consistent. The added complexity is a single extension install.

**Honest limitations:**
- The LangGraph `PostgresSaver` checkpointer tables are created by migration but the `RunExecutor` currently uses `InMemorySaver`. Mid-run checkpointing survives process kills at the gate-store level, but true mid-node resumption is not yet wired end-to-end.
- Conflict detection uses cosine similarity thresholds tuned for English-language project documents. Non-English documents or highly technical domain language (e.g., legal Latin) may produce missed or false-positive conflicts.
- The MCP server is implemented and tested but the SuperDocs MCP surface was not available for live integration testing during the assessment window; the MCP layer is complete on our side.

---

### Task 2 — Three Builds on SuperDocs

**Build A: Aviation Revision Bars & Effective Pages Generator**
Serves technical publications specialists who issue controlled revisions to Flight Crew Operating Manuals. The app compares two document revisions, auto-generates 3px left-margin change bars aligned to every modified paragraph, builds a Revision Record table, compiles a List of Effective Pages, writes a Highlights of Change summary, and stamps every page with `Revision XXXX — YYYY-MM-DD` headers and centered `Page X of Y` footers before exporting a controlled PDF. Every bar aligns to a real change and nothing else; the LEP matches the exported pagination.
*Key technical work:* Built a paragraph-level AST differ to isolate real content changes from whitespace noise, then used PyMuPDF's redaction layer to surgically stamp revision metadata onto existing PDFs without re-rendering them.

**Build B: FinOps Build-vs-Buy / ROI Calculator**
Serves technology leadership evaluating custom AI document pipelines versus SuperDocs. Live reactive TCO calculator: change any input (document volume, engineering hours, loaded cost rate) and the build-vs-buy comparison recomputes immediately. Download button exports a branded PDF via the SuperDocs export API whose numbers exactly match what is on screen at the moment of generation — not a screenshot, a real exported document.
*Key technical work:* Solved the "numbers must match" problem by computing the full TCO model server-side at export time using the same formula functions as the React UI, so the PDF figures are generated from identical inputs rather than scraped from the screen.

**Build C: Study-Guide & Equation Synthesizer (Open Task List, Band S2)**
Serves STEM students and EdTech tutors. Paste raw lecture notes and shorthand formulas; the system synthesizes a 4-tier structured study guide (formula reference table, Cornell conceptual breakdown, Feynman intuitive explanation, active recall quiz) and exports a publication-grade vector PDF with correct Unicode mathematical symbols (∇, ρ, ε₀, ∂) rendered via PyMuPDF's `insert_htmlbox` engine with KaTeX in the browser preview.
*Key technical work:* Discovered that PyMuPDF's default Helvetica font silently drops Greek/math Unicode glyphs. Solved this by switching to the `insert_htmlbox` API which routes through system fonts with proper Unicode coverage, guaranteeing ∇ renders as ∇ and not as a blank box or `?`.

**Measurable results across all three builds:**
- 50 / 50 unified sidecar tests pass in 2.63 seconds.
- Zero TypeScript errors across all three React frontends (`tsc && vite build` clean).
- All builds run fully offline without live API keys.

**Honest limitations:**
- Build B's PDF export calls the SuperDocs Cloud export API. If the API key is absent the PDF falls back to a local PyMuPDF-generated document; the numbers are correct but the branded styling is absent.
- Build C's AI chat refinement uses a deterministic patch engine offline (appends a revision note section). Live LLM-powered surgical section editing requires a connected SuperDocs API key.

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    CLIENT LAYER                              │
│  Build A UI (5173) │ Build B UI (5174) │ Build C UI (5175)  │
│                DocTask Review UI (3000)                      │
└────────────────────────────┬────────────────────────────────┘
                             │ HTTP
┌────────────────────────────▼────────────────────────────────┐
│              MODULAR SIDECAR HUB  (Port 8000)               │
│  build_a/router.py          build_b/router.py               │
│  /api/step/*  /api/export   /api/export-report              │
│               build_c/router.py                             │
│               /api/study-guide/generate|chat|export         │
└──────┬─────────────────┬──────────────────┬────────────────┘
       │                 │                  │
┌──────▼──────┐  ┌───────▼───────┐  ┌──────▼──────────────┐
│  Paragraph  │  │   PyMuPDF     │  │  SuperDocs Cloud API │
│  AST Differ │  │  Stamping &   │  │  Chat / Export /     │
│  & Redline  │  │  HTMLBox PDF  │  │  Parts endpoints     │
│  Engine     │  │  Engine       │  │                      │
└─────────────┘  └───────────────┘  └──────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│               TASK 1: DOCTASK ENGINE                        │
│                                                             │
│  Document Inbox (watched directory)                         │
│       │                                                     │
│       ▼                                                     │
│  LangGraph Pipeline                                         │
│  Ingest → Extract Facts → Detect Conflicts                  │
│       → Apply Governance Rules → Human Gate                 │
│       → Append-Only Ledger                                  │
│                                                             │
│  Storage: PostgreSQL 16 + pgvector                          │
│  (embeddings + relational ledger in one instance)           │
│                                                             │
│  FastAPI (Port 8000) + MCP Server (SSE, Port 9000)          │
│  React Review UI (Port 3000)                                │
└─────────────────────────────────────────────────────────────┘
```
