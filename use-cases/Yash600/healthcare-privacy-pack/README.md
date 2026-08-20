# Healthcare Compliance Workspace

A multi-tenant system for keeping a healthcare organization's policies and the procedures that
implement them provably in sync as requirements change -- built on SuperDocs.

There is **no hardcoded organization, no seed data, no demo pack anywhere in this codebase.**
Every `Workspace`, every `Document`, and every reference between a procedure and the specific
policy section it implements is created by a human, at runtime, through the API/UI. This is a
full rebuild of an earlier single-tenant version of this project that shipped with a fixed,
hand-authored policy pack; that version is gone.

## The core idea

Two separate pipelines, run at different times, for different reasons:

1. **Setup** -- a human creates a workspace, uploads real policy and procedure files (any
   format), groups each procedure under its parent policy, then triggers **Analyze References**:
   an LLM call (not a SuperDocs call -- see below) that reads every policy section and a
   procedure's full text and reports which procedure sections implement which policy sections,
   with a confidence score and a plain-English reason for each one. The result is stored as a
   graph in Postgres.
2. **Maintenance** -- a human edits a policy in plain language. SuperDocs proposes the change.
   Once approved, the system looks at exactly which policy sections changed (via a persisted
   chunk -> section map, no guessing from the prompt), queries the graph built in step 1, and
   proposes a matching edit to every procedure that references those sections -- each one an
   independent, human-reviewable SuperDocs job.

The graph built in step 1 is what makes step 2 fast and deterministic: finding "which procedures
does this policy section affect" is a database query, not a fresh LLM call every time something
changes.

## Where an LLM is used, and where it isn't

This distinction matters enough to be explicit about:

- **SuperDocs** owns every document *edit*: the initial parse/normalize on upload, every policy
  edit, every propagated procedure edit, and export. All of it goes through `chat` /
  `chat_async` + `ask_every_time` approval, exactly per the assignment's minimum integration
  (upload -> edit -> approve -> export).
- **A direct Groq API call** (`llm_client.py`, no SuperDocs involved) is used for exactly one
  thing: **Analyze References**. Given a policy's sections and a procedure's full text, it's
  asked to report `IMPLEMENTS` relationships as structured JSON (forced tool-use output), with a
  confidence score and evidence per relationship. This is classification, not editing -- it's
  the wrong job for SuperDocs' API, and routing it through `chat` would burn the account's
  operations quota on a phase of the system that doesn't need SuperDocs at all. Analyze
  References costs **zero SuperDocs operations**, regardless of workspace size.
- Everything else -- document-level grouping, mapping a changed chunk back to a section, finding
  affected procedures, validating the graph, generating reports -- is plain deterministic backend
  logic. No LLM, no SuperDocs, just database queries and equality checks.

## The database is the source of truth for everything

Every uploaded file's original bytes, every document version's full HTML, every section's full
text (not just a hash), every LLM-discovered relationship's full evidence text, and every
proposed change's before/after HTML are persisted in Postgres -- nothing is fetched from
SuperDocs on demand and thrown away. SuperDocs remains the engine that does the actual parsing
and editing, but the database is self-sufficient for history: reconstructing "what did this
document look like six approvals ago" never requires another SuperDocs call.

## Schema

17 tables, organized in four layers (see `backend/models.py` for the full definitions with
rationale in the docstrings):

```
Workspace
  └─ Document (POLICY or PROCEDURE; parent_policy_id groups a procedure under its policy)
       ├─ DocumentVersion   (1 = original upload w/ raw file bytes, N = every approved edit;
       │                      ACTIVE/PROPOSED/ARCHIVED/REJECTED)
       └─ Section           (STABLE identity across versions/edits/renames -- supports nested
            │                 numbering via parent_section_id, e.g. S4 -> S4.1)
            ├─ SectionSnapshot   (this version's chunk_id + full content + hash)
            └─ SectionRelation   (records a resolved split/merge lineage)

AnalysisRun -> AnalysisJob                     (one Analyze References run, one job per policy/procedure pair)
ProcedurePolicyReference                        (the graph edge -- confidence, evidence, both-side snapshot pins)
UpdateRequest -> ProposedChange                 (one SuperDocs proposal, policy or procedure; base_version_id
                                                  catches a stale-proposal race)
ValidationRun -> ValidationCheckResult          (per-run check log)
Finding                                         (persistent, dedupable problem record -- survives across runs)
Report, ChangeEvent, ExportRecord               (reporting + full audit trail)
```

Design decisions worth calling out: `Section` and `SectionSnapshot` are split on purpose -- a
section's *identity* (`Section`) never changes just because an edit changed its wording or its
underlying SuperDocs chunk id (`SectionSnapshot`), which is what lets "Policy §4" stay the same
logical thing across a hundred edits. `ProcedurePolicyReference` pins the exact snapshot on
*both* sides at confirmation time, not just the policy side, so a direct procedure edit outside
the propagation flow is caught too, not just policy drift. Structural reorganization (a section
splitting or merging) is deliberately never auto-detected -- the affected `Section` is flagged
`NEEDS_REANALYSIS` and left for a human to resolve via `SectionRelation`, rather than guessed at.

## What actually happens, end to end

**Setup**

1. `POST /workspaces` -- create a workspace (organization name/type, pack name). Nothing else
   exists yet.
2. `POST /workspaces/{id}/documents/upload` -- a human uploads one file at a time: a policy, or a
   procedure grouped under a policy via `parent_policy_id`. SuperDocs parses whatever format was
   uploaded (docx/pdf/html/md/txt/rtf) into normalized HTML; the backend extracts headings/chunks
   itself (via `chunking.py`, no SuperDocs `structure` field needed since we already have the
   HTML) and creates a `Section`/`SectionSnapshot` per heading. The *document-level* grouping
   (which policy a procedure belongs to) is 100% human-decided here, zero AI -- exactly per the
   architecture discussion: don't ask AI to figure out something the human already knows.
3. `POST /workspaces/{id}/analyze` -- Analyze References. Creates one `AnalysisJob` per
   (policy, procedure) pair already grouped, runs them under a concurrency-limited thread pool
   (default 3 concurrent), and each job makes exactly one direct Groq API call with the full
   policy section set + full procedure text, writing confidence-gated
   `ProcedurePolicyReference` rows (>=0.85 confidence -> `VALID` automatically; 0.5-0.85 ->
   `NEEDS_REVIEW`, surfaced to a human rather than silently trusted; below 0.5 -> discarded).
4. `POST /workspaces/{id}/validate` -- an independent re-check, entirely against the persisted
   database (no SuperDocs calls needed at all, since full content already lives in Postgres):
   every procedure has a parent policy, every reference resolves to active sections, pinned
   content hashes still match the live section on both sides, low-confidence references are
   still unreviewed, and a best-effort heuristic flags numeric/time-unit mismatches between a
   policy section and the procedure section that's supposed to implement it (e.g. policy says
   "24 hours", procedure still says "60 hours"). Anything that fails becomes a persistent
   `Finding`, deduplicated across runs.

**Maintenance**

5. `POST /documents/{id}/update-requests` -- a human picks a document (policy or procedure) and
   describes a change in plain language. This creates an `UpdateRequest` and submits the
   instruction via `chat_async` with `ask_every_time` -- every edit, policy or procedure, goes
   through the same human-review gate, not just propagated ones.
6. `GET /workspaces/{id}/proposed-changes` -- the review queue. Polls SuperDocs for any job that
   has reached `awaiting_approval` and fills in the diff (`old_html`/`new_html`) the first time
   it's seen, persisting it rather than re-fetching on every view.
7. `POST /proposed-changes/{id}/approve` -- approve or reject one change independently.
   - **Approved policy edit**: fetches the full updated document, creates a new `DocumentVersion`
     (archiving the prior one), re-syncs `Section`/`SectionSnapshot` (matching by chunk id first,
     then by heading text, flagging anything unmatched as `NEEDS_REANALYSIS` rather than
     guessing), determines exactly which sections' content actually changed, and for every
     `ProcedurePolicyReference` pointing at a changed section: flags it `STALE`, opens an
     `OUTDATED_REFERENCE` finding, and fires an independent `chat_async` proposal to that
     procedure embedding the specific new policy wording.
   - **Approved procedure edit** (whether standalone or a propagated one): creates its new
     version the same way, and if it was propagated, re-pins both snapshots on the reference,
     flips it back to `VALID`, and resolves the finding that was opened for it.
   - **Rejected policy edit**: nothing downstream ever happens -- no version, no propagation, no
     procedure ever gets touched. Partial approval across a batch of propagated procedure
     proposals is fully supported, since each one is an independent job.
8. `POST /workspaces/{id}/reports` -- rolls up document/reference/finding/pending-review counts
   into a versioned report (`v1.0`, `v1.1`, ...).
9. `GET /workspaces/{id}/export` -- zips every document's **active** version plus the latest
   report. A `PROPOSED` (unapproved) version can never end up in an export by construction, since
   export only ever reads `active_version_id`.

## SuperDocs features used

The card for this build names three surfaces: **templates, Multi-document, export.**

- **templates** -- `POST /v1/templates/upload-base64` uploads a small library of structural
  skeletons (`main.py`'s `TEMPLATE_LIBRARY`: a policy template and a procedure template, headings
  only, no policy language -- see that constant's docstring for why real content there would
  quietly reintroduce the "hardcoded pack" this project deliberately doesn't have). `GET
  /v1/templates` lists what's uploaded (`_ensure_templates_uploaded` is idempotent -- it lists
  first and only uploads what's missing, so calling it repeatedly costs one free GET, not a
  re-upload). `POST /v1/chat` with no `document_html` (see docs.superdocs.app/concepts/documents,
  "Creating documents from scratch") lets the AI draft a brand-new document, searching the
  account's uploaded templates for a starting point -- this is `POST
  /workspaces/{id}/documents/draft`, a second document-creation path alongside file upload, exposed
  in the sidebar as "Draft with AI".
- `POST /v1/documents/upload-base64` -- the primary ingestion path; every policy/procedure a human
  uploads
- **Multi-document** -- every `Document` gets its own dedicated SuperDocs session
  (`superdocs_session_id`); `list_session_documents` + `get_document` resolve the durable id and
  canonical persisted HTML right after upload/draft, and again after every approved edit
- `POST /v1/chat/async` + `POST /v1/chat/{session_id}/approve` -- the human-gated edit loop
  (Analyze References findings -> proposed changes -> approve/reject)
- **export** -- `POST /v1/documents/export`, called per-document and rolled into the workspace-wide
  zip
- `GET /v1/documents/{id}` (+ `include_html=true`) -- non-billable structure/heading checks used by
  the validator and by both document-creation paths to fetch canonical HTML

## Architecture

```
backend/
  superdocs_client.py   SuperDocs REST client: upload-base64, chat, chat/async + approve
                         (handles the documented double-JSON-parse gotcha), sessions,
                         export, templates, poll-with-backoff
  llm_client.py           direct Groq API client, used ONLY for Analyze References --
                          forced tool-call JSON output, kept entirely off SuperDocs' billable
                          surface (see "Where an LLM is used" above)
  models.py               17-table SQLModel schema (Workspace through ExportRecord)
  db.py                   Postgres via a real DATABASE_URL (Neon by default -- see
                          .env.example), falling back to an embedded Postgres (`pgserver`)
                          automatically if DATABASE_URL is left unset
  chunking.py             pure functions: chunk extraction, heading extraction, content
                          hashing -- the deterministic core of the staleness model
  main.py                 FastAPI app: every endpoint described above
  tests/
    fakes.py               FakeSuperDocsClient + FakeLLMClient -- no live keys needed
    test_main.py            full end-to-end lifecycle test against the fakes: workspace ->
                            upload -> group -> analyze -> validate -> update -> approve ->
                            propagate -> approve -> report -- plus reject/low-confidence/
                            missing-reference edge case tests
    test_chunking.py        pure-function tests for the chunking module
frontend/
  app/page.tsx                          Home -- list/create workspaces
  app/w/[workspaceId]/page.tsx           Workspace -- upload, document list, Analyze
                                         References, references graph, open findings
  app/w/[workspaceId]/update/page.tsx    Update & Review -- submit an instruction, review
                                         and approve/reject pending proposals, in one screen
  app/w/[workspaceId]/export/page.tsx    Report & Export
  app/documents/[id]/page.tsx            Document detail -- sections + its references
```

## Running it

### Backend

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate   # skip if .venv already exists
pip install -r requirements.txt
cp .env.example .env
# edit .env: set SUPERDOCS_API_KEY (free signup, see .env.example), GROQ_API_KEY (free key
#            at console.groq.com -- required for Analyze References specifically, everything
#            else works without it), and DATABASE_URL (your Neon connection string)
python3 -m uvicorn main:app --reload --port 8000
```

`DATABASE_URL` is a real Neon Postgres connection string (create a project at
console.neon.tech, paste its connection string in -- `db.py` treats it like any other
Postgres server, nothing Neon-specific in the code). Leaving `DATABASE_URL` unset falls back
to an embedded Postgres via `pgserver` instead -- a real `postgres` binary, no Docker, no
root, data under `~/.healthcare_compliance_workspace/pgdata` -- handy for a quick run without
a Neon project set up yet. Tables are created automatically on startup either way -- there is
no seed step; the first thing to do against a fresh database is `POST /workspaces`.

Run tests (no live keys, no external Postgres required -- everything runs against an in-memory
SQLite database and fake SuperDocs/LLM clients):

```bash
pytest -v
```

### Frontend

```bash
cd frontend
npm install
cp .env.local.example .env.local   # NEXT_PUBLIC_API_BASE=http://localhost:8000
npm run dev
```

Open `http://localhost:3000`, create a workspace, upload a policy and a procedure grouped under
it, click **Analyze References**, then try an update from the **Update & Review** tab.

## Data model summary

- **Workspace** -- top-level tenant (organization + pack name + status).
- **Document** -- a policy or procedure; content-free, points at its active `DocumentVersion`.
- **DocumentVersion** -- a full persisted snapshot (original file bytes on v1, full HTML on
  every version); old ones are archived, never deleted or overwritten.
- **Section / SectionSnapshot** -- stable logical identity vs. its per-version realization.
- **ProcedurePolicyReference** -- the graph edge: confidence, evidence, status, both-side
  snapshot pins.
- **AnalysisRun / AnalysisJob** -- the Analyze References job tree.
- **UpdateRequest / ProposedChange** -- one user instruction, one or more SuperDocs proposals.
- **ValidationRun / ValidationCheckResult / Finding** -- the independent re-check, and the
  persistent worklist of problems it surfaces.
- **Report / ChangeEvent / ExportRecord** -- reporting and full audit trail.
