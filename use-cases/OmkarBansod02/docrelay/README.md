# DocRelay

**Safe AI write-back for cloud documents.**

Teams keep important documents in Google Drive. DocRelay lets SuperDocs prepare AI-assisted edits while Google Drive remains authoritative: every supported write is explicitly reviewed, backed up, revision-guarded, re-read, and structurally verified before success is reported.

Built by Omkar Bansod for the SuperDocs Engineer Task.

## Screenshot

![DocRelay review workbench](./assets/docrelay-workbench.png)

## Why DocRelay

Cloud documents are authoritative, but AI editing workflows often end in a manual upload/download cycle or a whole-file replacement that can erase concurrent human work and unrelated structure.

Generating a change is not the hard part. The hard part is returning a reviewed change to the original cloud document only when its source revision, permissions, mapping, backup, and resulting structure can all be proved. DocRelay is the control plane for that boundary; SuperDocs remains the editing and review engine.

## What it does

- Captures an explicitly selected native Google Doc and freezes its revision, native canonical form, and DOCX export.
- Sends that frozen DOCX to SuperDocs for an async, human-in-the-loop edit job.
- Persists proposals and requires an approve/reject decision for every proposal in the current review round.
- Maps only a deliberately narrow, uniquely provable Google Docs text-replacement subset.
- Produces a sealed `MappingProof` and `WritePlan`; dry-run reports the exact intended operations without mutating Google.
- Creates and verifies a separate Google Drive backup before the authoritative mutation.
- Applies one `documents.batchUpdate` guarded by Google Docs `requiredRevisionId`.
- Re-reads the entire native document and compares it with the expected canonical postimage.
- Reconstructs a document-scoped conversation from durable run history and supports reviewed DOCX export.
- Discovers eligible documents on scheduled Google Drive folder scans and routes each into the same review/write pipeline.
- Exposes the same domain workflow over REST and stateless Streamable HTTP MCP.

## The safety contract

```text
Google revision A
      ↓
Frozen baseline (native structure + DOCX)
      ↓
SuperDocs proposal
      ↓
Human review
      ↓
MappingProof + sealed WritePlan
      ↓
Permission + revision check
      ↓
Independent Google Drive backup
      ↓
requiredRevisionId guarded write
      ↓
Full provider re-read + canonical comparison
      ↓
WRITE_VERIFIED
```

The commit path is intentionally strict:

1. Read Google Docs revision A, export DOCX, and read the revision again; accept the capture only when both opaque revision IDs match.
2. Re-capture before starting a run and freeze the native hashes, canonical payload, DOCX hash, provider identity, and revision.
3. Upload that artifact to a fresh SuperDocs session and start an explicitly targeted `ask_every_time` edit.
4. Persist each proposal and every explicit review decision.
5. Normalize only approved edits and prove each Google-native range uniquely. Unsupported or ambiguous approved changes stop the entire plan.
6. Seal the approval lineage, baseline, exact provider requests, and complete expected postimage into a deterministic WritePlan.
7. Immediately before backup, re-check identity, revision, native hashes, structure, write/copy capabilities, and—on watched runs—the frozen root path and exact-file authorization.
8. Create a same-parent Drive copy and verify that it is separate, independently readable, structurally equal to the baseline, correctly located, and no broader in effective permissions.
9. Re-check the source after backup, then submit one native batch update with revision A as `requiredRevisionId`.
10. Re-read Google Docs and report `WRITE_VERIFIED` only when identity, advanced revision, intended ranges, and the complete canonical postimage all match.

**If DocRelay cannot prove a mutation is safe, it does not write it.**

External effects are checkpointed before dispatch. When a backup or write response is lost, DocRelay records an `UNKNOWN` outcome and reconciles observable provider state where that is safe; it does not blindly retry an effect that may already have happened. An unknown backup-copy outcome remains an operator-attention state because there is no proven safe way to discover the exact copy.

## Concurrency: the failure case we designed for

```text
T0  DocRelay reads Google revision A
T1  SuperDocs prepares edits based on A
T2  A person edits the Google Doc → revision B
T3  DocRelay attempts to commit its A-based plan
```

DocRelay compares the current opaque Google Docs revision before backup and again after backup. The actual write also carries `writeControl.requiredRevisionId = A`, so a last-moment race is rejected by Google rather than converted into a stale overwrite. Revision B remains authoritative.

A conflict is durable and offers only explicit `CANCEL` or `REVIEW_LATEST` choices. Neither choice executes the stale plan; V1 does not perform an automatic merge.

## Architecture

```mermaid
flowchart LR
    UI[Next.js review workspace] <--> API[FastAPI REST + MCP]
    Worker[Workflow / Watch worker] --> Domain[DocRelay domain services]
    API --> Domain
    Domain <--> DB[(PostgreSQL workflow and effect state)]
    Domain <--> Artifacts[(Private baseline / export artifacts)]
    Domain <--> Google[Google Drive + Docs]
    Domain <--> SuperDocs[SuperDocs REST API]
```

FastAPI owns the web and machine interfaces. Domain services own review, mapping, planning, Watch, and write-back policy. PostgreSQL stores workflow transitions, immutable evidence lineage, idempotency keys, scan claims, conflicts, and external-effect outcomes. The worker resumes SuperDocs jobs and claims scheduled Watch scans from the same durable state. The local filesystem artifact store holds hashed baseline and reviewed DOCX files; multi-process deployment requires shared protected durable storage for that directory.

## Why Google Drive + native Google Docs

The V1 provider was selected for the safety primitives it exposes:

- Google Drive is the real cloud source of truth, selected through OAuth and Google Picker.
- Google Docs exposes an opaque editor revision ID used as concurrency authority.
- `documents.batchUpdate` supports surgical `deleteContentRange` and `insertText` operations plus `requiredRevisionId` write control.
- `drive.files.copy` creates an independently addressable backup instead of treating revision history as the backup.
- Drive metadata exposes the edit/copy capabilities and file authorization needed for fail-closed permission checks.

The implementation does not substitute filenames, paths, `modifiedTime`, or sortable revision assumptions for provider identity and concurrency authority.

## SuperDocs integration

For each cloud revision, DocRelay freezes a freshly captured DOCX and uploads it to a new SuperDocs session. It verifies the returned session/document roster, starts `/chat/async` against that exact document with `approval_mode=ask_every_time`, and persists the job identity before polling.

Pending change batches become durable proposals. DocRelay submits the complete per-item decision set to SuperDocs, handles an explicit continuation prompt when returned, waits for actual job completion, focuses the exact target document, and exports a hashed reviewed DOCX. Restart recovery reconciles the same session/job where provider state can prove the outcome; uncertain upload, paid job-start, review, or focus effects are quarantined rather than casually repeated.

SuperDocs is responsible for document editing, proposals, Review, continuation, and export. DocRelay owns the Google baseline, authorization, mapping proof, backup, guarded write, and post-write verification. The reviewed DOCX is evidence and a downloadable artifact; it is not uploaded wholesale over the Google Doc.

## Review and dry-run

Every current proposal must receive an explicit approve or reject decision. Rejected proposals are retained as review evidence but do not enter the WritePlan. Multiple approved edits can share one plan only when every edit is independently supported and their frozen Google ranges do not overlap; requests are ordered from the highest baseline index to the lowest so variable-length replacements do not invalidate later coordinates.

Dry-run builds or recovers the deterministic MappingProof and WritePlan and returns the exact source revision, mapped ranges, before/after text, planned Google requests, backup action, and verification checks. The dry-run service performs no Google backup or content mutation. SuperDocs processing happens earlier in the workflow and can still consume SuperDocs/model usage even if the user stops after dry-run.

## Structural fidelity

DocRelay makes a programmatic, bounded claim—not a visual claim about arbitrary Google Docs fidelity.

The canonical baseline retains tabs, body structure and indexes, paragraphs, runs and styles, links, lists, tables, headers, footers, footnotes, section/document properties, named styles/ranges, and inline/positioned objects while removing suggestion overlays. Planning applies only the intended range operations to a copy of that frozen canonical value to derive the expected postimage.

After writing, DocRelay fetches the complete native Google document again. Verification requires the expected schema and canonical hash, exact canonical payload equality, new text at every intended range, removal of each old preimage, unchanged provider identity, and an advanced revision. Any unrelated structural difference produces `VERIFICATION_FAILED`, never `WRITE_VERIFIED`.

## Real versioned backup

Before changing the source, DocRelay creates a separate native Google Doc with `drive.files.copy` in the source's proven My Drive parent. It ties the copy to the run/plan through app properties and persists its opaque file ID.

The copy must then be independently readable and prove all of the following: different file identity, native Google Docs MIME type, expected parent, complete canonical equality with the frozen baseline, and effective permissions no broader than the source. A failed or unprovable backup blocks the authoritative write. DocRelay does not mutate ACLs to make a backup pass.

## Watch Mode

```text
Selected owned My Drive folder
  → interval scan
  → recursive, parent-bounded discovery
  → nearest enabled ancestor rule
  → one frozen version + one independent run per changed document
  → SuperDocs proposal and explicit human review
  → the same dry-run / backup / guarded-write / verification path
```

Watch supports persisted interval schedules from 60 seconds to 24 hours (five minutes by default), manual scans, paginated recursive discovery, scan leases/recovery, and a configured maximum item count. Rules are immutable versions attached to folders inside the selected root; the nearest enabled ancestor rule wins and is snapshotted onto the discovered document version.

The `(watched item, provider version)` checkpoint and database uniqueness constraints deduplicate repeated or concurrent scans of the same version. Discovery uses the explicit Watch OAuth profile (`openid + drive.file + drive.readonly`), stays within an owned My Drive root, and rejects Shared Drives, shared-with-me roots, cycles, duplicate identities, incomplete searches, and items that move during capture.

Watch never implies approval or write authority. It creates independent runs that surface for human review. Because read-only folder discovery does not grant `drive.file` write authority, each watched source must be selected/confirmed through Picker before backup or write-back, and the entire frozen root path is revalidated at the commit boundary.

## Machine interface

FastAPI exposes compact REST resources under `/api/v1` for Google connections/sources, runs, review, dry-run, authorization, conflict decisions, export, and Watch. Development OpenAPI is available at `/api/docs`.

The same application services are mounted as a stateless Streamable HTTP MCP server at `/mcp`. MCP can inspect scans/runs, submit explicit review decisions, prepare dry-runs, verify exact-file authorization, invoke write-back, resolve conflicts, and retrieve reviewed-export metadata. It cannot bypass the same review lineage, authorization, backup, revision, or verification gates used by the UI and REST API.

## Multi-document

“Multi-document” currently means a Watch scan can discover and track many documents, create one durable independent run per eligible document version, and present grouped scan/root summaries. Runs do not share approval or write state, so one document's conflict or failure does not corrupt a sibling run.

There is no cross-document reasoning, shared SuperDocs multi-document editing session, batch approval, or batch write. Each source is ingested into its own SuperDocs session and committed independently. This keeps cloud revision and human-review authority unambiguous.

## Tech stack

| Layer | Main technologies |
|---|---|
| Backend | Python 3.12+, FastAPI, Pydantic, SQLAlchemy async, Alembic |
| Durable state | PostgreSQL 17; private filesystem artifact store |
| Frontend | Next.js 16, React 19, TypeScript, Tailwind CSS, shadcn/Radix components |
| Integrations | Google Drive API, Google Docs API, Google Picker/GIS, SuperDocs REST API |
| Machine interface | REST/OpenAPI and MCP Streamable HTTP |

## Quick start

### Prerequisites

- Python 3.12–3.14 and [uv](https://docs.astral.sh/uv/)
- Node.js 20.9+ and npm
- Docker with Compose
- A SuperDocs API key for edit/review/export workflows
- A Google Cloud project for real Google selection and write-back

### 1. Configure the environment

```bash
cp .env.example backend/.env
cp frontend/.env.local.example frontend/.env.local
```

Fill in the documented placeholders; never put server secrets in `frontend/.env.local`.

For Google, enable the Drive, Docs, and Picker APIs. Create a Web application OAuth client with this local redirect URI:

```text
http://localhost:8000/api/v1/google/oauth/callback
```

Generate a Fernet keyring for encrypted server-side OAuth credential storage:

```bash
cd backend
uv run python -c 'import json; from cryptography.fernet import Fernet; print(json.dumps({"v1": Fernet.generate_key().decode()}))'
```

Place the generated value in `OAUTH_TOKEN_ENCRYPTION_KEYS` in `backend/.env`. The frontend additionally needs the public OAuth client ID, a browser-restricted Picker API key, and the Google Cloud project number.

### 2. Start PostgreSQL and migrate

From the repository root:

```bash
docker compose up -d postgresql

cd backend
uv sync --all-groups
uv run alembic upgrade head
```

### 3. Start the backend and worker

Backend terminal, from `backend/`:

```bash
uv run uvicorn docrelay.main:app --reload --port 8000
```

Worker terminal, also from `backend/`:

```bash
uv run python -m docrelay.worker
```

The worker resumes SuperDocs jobs and scheduled Watch scans. API and worker must share `DATABASE_URL` and `DOCRELAY_ARTIFACT_DIR`.

### 4. Start the frontend

```bash
cd frontend
npm ci
npm run dev
```

Open [http://localhost:3000](http://localhost:3000). Backend liveness/readiness are available at `/health/live` and `/health/ready` on port 8000.

## Configuration

See [`.env.example`](.env.example) and [`frontend/.env.local.example`](frontend/.env.local.example) for public-safe starter templates. Variables omitted from the templates use the defaults documented in `backend/src/docrelay/core/config.py`.

| Group | Important variables |
|---|---|
| Database/runtime | `DATABASE_URL`, `DOCRELAY_ARTIFACT_DIR`, `DOCRELAY_OWNER_SUBJECT`, `APP_ENV`, `LOG_LEVEL` |
| SuperDocs | `SUPERDOCS_API_KEY`, `SUPERDOCS_API_BASE`, `SUPERDOCS_HTTP_TIMEOUT_SECONDS`, `PHASE3_WORKER_POLL_SECONDS` |
| Google server | `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, `GOOGLE_OAUTH_REDIRECT_URI`, `OAUTH_TOKEN_ENCRYPTION_KEYS`, `OAUTH_TOKEN_ENCRYPTION_PRIMARY_VERSION` |
| Frontend/Picker | `NEXT_PUBLIC_DOCRELAY_API_URL`, `NEXT_PUBLIC_GOOGLE_OAUTH_CLIENT_ID`, `NEXT_PUBLIC_GOOGLE_PICKER_API_KEY`, `NEXT_PUBLIC_GOOGLE_CLOUD_PROJECT_NUMBER` |
| Browser/MCP policy | `CORS_ORIGINS`, `MCP_ALLOWED_HOSTS`, `MCP_ALLOWED_ORIGINS` |
| Watch bounds | `WATCH_WORKER_CLAIM_LIMIT`, `WATCH_SCAN_LEASE_SECONDS`, `WATCH_MAX_ITEMS_PER_SCAN` |

The normal single-file OAuth profile requests `openid + drive.file`. Enabling Watch requires a separate explicit authorization profile that adds the restricted `drive.readonly` scope. OAuth credentials are stored server-side in an authenticated-encrypted envelope; browser Picker tokens remain in memory and are not sent to the backend.

## Testing

### Deterministic/local tests

These checks use fakes or SQLite where appropriate and require no Google or SuperDocs credentials:

```bash
cd backend
uv run pytest -m 'not live_google and not live_superdocs and not postgresql'
uv run ruff check src tests alembic
uv run ruff format --check src tests alembic
uv run mypy src

cd ../frontend
npm test
npm run typecheck
npm run lint
```

The deterministic suite covers zero-mutation dry-run, complete/mixed review, unique and multi-approved mapping, stale revisions before/after backup and at the atomic guard, backup/ACL failure, unknown outcomes, restart and concurrent execution, exact postimage verification, Watch scheduling/deduplication/path movement, and REST/MCP gate parity.

Run PostgreSQL-specific constraints, indexes, JSONB, and immutable-trigger verification after starting the Compose service:

```bash
cd backend
DOCRELAY_TEST_POSTGRES_URL=postgresql+asyncpg://docrelay:docrelay@localhost:5432/docrelay \
  uv run pytest -m postgresql
```

### Live integration verification

Live checks are opt-in and must use synthetic/public-safe files. Complete backend OAuth first; the tests take persisted UUIDs and opaque file IDs, never copied access tokens.

Read/capture Google verification:

```bash
cd backend
DOCRELAY_RUN_LIVE_GOOGLE=1 \
DOCRELAY_LIVE_GOOGLE_CONNECTION_ID=connection-uuid \
DOCRELAY_LIVE_GOOGLE_FILE_ID=native-google-doc-id \
DOCRELAY_LIVE_GOOGLE_UNSUPPORTED_FILE_ID=unsupported-file-id \
uv run pytest -q tests/test_google_live.py
```

SuperDocs upload → review → restart recovery → export verification:

```bash
DOCRELAY_RUN_LIVE_SUPERDOCS=1 \
DOCRELAY_LIVE_GOOGLE_SOURCE_ID=source-uuid \
DOCRELAY_LIVE_GOOGLE_BASELINE_CAPTURE_ID=capture-uuid \
uv run pytest -q tests/test_superdocs_live.py
```

Bounded real Google backup/write and stale-conflict verification:

```bash
DOCRELAY_RUN_LIVE_PHASE6=1 \
DOCRELAY_LIVE_PHASE6_SUCCESS_FILE_ID=dedicated-success-google-doc-id \
DOCRELAY_LIVE_PHASE6_CONFLICT_FILE_ID=dedicated-conflict-google-doc-id \
uv run pytest -q tests/test_phase6_live.py
```

This test intentionally requires two dedicated synthetic native Google Docs: it creates a real backup, writes the success document, and simulates a concurrent edit in the conflict document. The repository records a live single-replacement success and stale-write rejection. A Watch-origin document has additionally been taken manually through restricted-scope discovery, exact-file authorization, and verified write-back, and a concurrent human edit was manually confirmed to stop at `GOOGLE_SOURCE_REVISION_CONFLICT` before any overwrite. A live multi-approved write remains manual/pending evidence.

## Supported scope and limitations

DocRelay deliberately prefers a bounded proven write subset over best-effort mutation of arbitrary Google Docs structure.

- V1 targets explicitly authorized native Google Docs in My Drive-compatible locations with one provable parent; Watch roots must be owned My Drive folders. Uploaded DOCX/PDF, Sheets, Slides, Shared Drives, shared-with-me Watch roots, and multi-parent/ambiguous backup destinations are not write-back targets.
- A writable replacement must be a unique ordinary-ASCII text span in a top-level, non-list body paragraph whose named style is `NORMAL_TEXT`, `TITLE`, `SUBTITLE`, or `HEADING_1`–`HEADING_6`, represented by one plain text run with no formatting delta. Internal, prefix, suffix, and full visible-block replacements, variable UTF-16 lengths, and multiple non-overlapping approved replacements are supported.
- Tables, lists, headers/footers, multi-block structural transformations, multi-run or styled-span edits, creates/appends/deletes, non-ASCII replacements, overlapping ranges, and ambiguous repeated preimages fail closed. Those structures are still retained and compared during post-write verification.
- The document preview is a read-only rendering of the frozen canonical source, not a replacement Google Docs editor and not visual fidelity proof.
- Watch requires the restricted `drive.readonly` scope for unattended discovery. The code enforces a selected owned-root boundary, but production use still requires the applicable Google verification, security, privacy, and retention work.
- Watch deduplicates an already-enqueued provider version. It does not currently persist a dedicated suppression marker for the new provider version created by DocRelay's own successful write, so post-write self-trigger suppression is not claimed.
- Watched documents require exact-file Picker authorization before write-back because discovery authority is not write authority.
- Multi-document support is multiple independent document runs and grouped summaries, not cross-document reasoning or a shared SuperDocs session.
- The UI conversation is reconstructed from durable instructions and run outcomes; it is not a general free-form chat history independent of document runs.
- Outcome-uncertain provider and SuperDocs effects are reconciled or quarantined, never assumed successful and never automatically repeated without proof. An unknown backup copy requires operator attention.
- Application-user authentication, tenant isolation, role-based access control, and a production authorization boundary are not implemented. `DOCRELAY_OWNER_SUBJECT` models one trusted application owner for this vertical slice.
- The default artifact store is local disk. Multiple processes or hosts require a protected shared durable artifact directory.

## Engineering trade-offs

1. **Cloud remains authoritative.** Each new cloud revision starts from a fresh capture and SuperDocs ingestion; neither the local preview nor SuperDocs durable state replaces Google.
2. **Native surgical writes over file replacement.** DocRelay compiles exact ranges to Google Docs operations and never falls back to global text replacement or whole-document upload.
3. **Proof before breadth.** Unsupported structure stops planning instead of widening the mapper heuristically.
4. **Durable effects over in-memory orchestration.** PostgreSQL checkpoints intent before external calls so restart recovery can reconcile instead of guess.
5. **Human approval before mutation.** Watch and machine interfaces can discover and prepare work, but cannot turn discovery into implicit approval.
6. **Unknown is a first-class outcome.** An ambiguous external response is safer as attention/reconciliation state than as an automatic retry.

## Repository layout

```text
backend/
  src/docrelay/        FastAPI, domain services, provider adapters, MCP, worker
  alembic/             PostgreSQL schema and immutable-evidence migrations
  tests/               deterministic, PostgreSQL, and opt-in live verification
frontend/
  app/                 Next.js workspace, Watch, runs, review, and write-back UI
  __tests__/           Vitest interaction and safety-state coverage
docker-compose.yml     local PostgreSQL 17
```

## Built for the SuperDocs Engineer Task

Built by Omkar Bansod for the SuperDocs Engineer Task. This submission implements the assigned **Cloud-storage knowledge sync with write-back** use case: real Google cloud reads, SuperDocs-assisted reviewed edits, recoverable backup, guarded same-document write-back, structural verification, scheduled folder discovery, and human/machine control surfaces—with the bounded scope and remaining live-proof conditions documented above.
