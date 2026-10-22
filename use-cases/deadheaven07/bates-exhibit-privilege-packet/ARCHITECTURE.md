# Architecture

## 1. System Context

**Bates Exhibit & Privilege Packet Builder** is a legal e-discovery application. Legal teams upload exhibit files (PDF, DOCX, scanned PDFs, images), and the system produces a single reconciled PDF **packet** consisting of:

- a **Bates-numbered** set of exhibits with cover sheets and a contiguous numbering scheme,
- a **privilege log** (human- and machine-readable),
- a **redacted** final PDF and per-exhibit PDFs with PII removed and verified (text-searchable), and
- a `manifest.json` of **SHA-256** hashes that independently proves the exported packet's integrity.

The frontend is a React workspace; the backend is a FastAPI service over PostgreSQL and the filesystem; AI review is delegated to the SuperDocs API through an adapter.

## 2. High-Level Architecture

```mermaid
flowchart LR
    UI[React Frontend] --> API[FastAPI API]
    API --> DB[(PostgreSQL)]
    API --> FS[File Storage]
    API --> SD[SuperDocs AI]
```

```
Frontend (React + TypeScript)
        │  HTTPS (Axios)
        ��
��─────────────────────��
│   FastAPI API        │
│  (async, background   │
│   BackgroundTasks)   │
��─────────��───────────��
          │
   ��────────────��─────────────────────────��──────────��
   ��            ��                         ��          ��
Application/   Domain (SQLAlchemy ORM)   File       PostgreSQL
Services:                            Storage    storage/ originals, processed,
  ingestion, redaction,            (final,     working, final
  bates, builder,                   covers,       │
  SuperDocs integration            index,
                                    exhibits)
          │
          ��
   SuperDocs Adapter (SuperDocsPort + SuperDocsRESTAdapter)
          │
          ��
   SuperDocs REST API
```

## 3. Backend Architecture

The backend is split into clearly separated layers (under `backend/app/`):

- **`api/`** — FastAPI routers. Each router owns one resource: `packets`, `documents`, `processing`, `review`, `privilege`, `redactions`, `bates`, `exports`, `search`, `audit`, `health`. Routers handle HTTP concerns only: input validation (Pydantic models), dependency injection of the DB session and the SuperDocs service, and response shaping. Background work (ingestion, redaction detection) is scheduled with FastAPI `BackgroundTasks`.
- **`services/`** — application use cases and infrastructure adapters:
  - `ingestion.py` validates uploads, detects type, and converts DOCX/images to PDF.
  - `redaction.py` detects PII, reconciles candidates (idempotent upsert), and applies/verifies redactions with PyMuPDF.
  - `bates_assignment.py` assigns and manages contiguous Bates numbers.
  - `packet_builder.py` assembles the final packet, cover sheets, exhibit index, privilege log, and manifest.
  - `storage.py` provides reference-aware (de)allocation helpers for original/processed/working/final files.
  - `superdocs_adapter.py` (`SuperDocsRESTAdapter`) and `superdocs_integration.py` (`SuperDocsIntegrationService`) implement the `superdocs_port.SuperDocsPort` interface.
- **`domain/`** — SQLAlchemy ORM models + enums. Pure data/invariant layer; no IO, no business orchestration. Relationships map the real ownership graph.
- **`workers/processor.py`** — `process_document`, the asynchronous per-document processing background job (type detection, PDF conversion, text extraction, OCR). It is the retry entry point: re-running it on a document whose conversion failed keeps the document `FAILED` rather than silently flipping it to `completed`.
- **`main.py`** — FastAPI factory: CORS, router registration, `lifespan` that ensures storage directories exist and initializes the database.
- **`config.py`** / **`database.py`** — `pydantic-settings` `Settings` and the async engine/session lifecycle.
- **`time.py`** — `utc_now()` helper used by domain defaults and cover sheets.

## 4. Domain Model

All entities live on a single `Base` metadata (see `app/domain/*.py`). Ownership:

| Entity | Ownership | Notes |
|---|---|---|
| `Packet` | root | owns documents, bates assignments, privilege decisions, audit events, one manifest |
| `Document` | belongs to Packet | owns pages, bates_assignments, redaction_candidates/approvals, privilege_decisions, audit events |
| `Page` | belongs to Document | one row per PDF page |
| `BatesAssignment` | belongs to Packet+Document, references Page | `bates_number`, `bates_label` |
| `RedactionCandidate` | belongs to Document | PII match + coordinates + identity |
| `RedactionApproval` | belongs to Candidate (1:1) | status, approver, verification |
| `PrivilegeDecision` | belongs to Packet+Document | status/category/reason/reviewer |
| `Manifest` | belongs to Packet | packet-level hashes + generated_at |
| `ManifestEntry` | belongs to Manifest + Document | per-document hashes, bates range, privilege info, applied_redactions |
| `AuditEvent` | belongs to Packet (optionally Document) | `event_type`, `user_id`, `event_metadata` (JSON) |

Foreign keys use `ondelete="CASCADE"` for documents (deletion cascades) and `SET NULL` for `audit_events` so audit history survives packet deletion.

## 5. Document Lifecycle

A document progresses through `ProcessingStatus` values defined in `app/domain/document.py`:

```
queued  →  processing  →  ocr  →  bates_assigned
  → [ai_analysis / waiting_review / approved]   (SuperDocs AI, when requested)
  → completed   (ready to include in a packet build)
  → failed      (with processing_error + last_completed_step)
```

- A failure at any stage transitions the document to `failed` with a `processing_error` and a `last_completed_step`.
- DOCX whose conversion tool (LibreOffice) is unavailable becomes `failed` with a "LibreOffice unavailable" message (never falsely `completed`).
- AI analysis failure reverts the document to `completed` (see §11) so it is never stuck in `ai_analysis`.

## 6. Redaction Architecture

- **Detection** (`RedactionDetectionService.detect_in_pdf`) runs per-page text extraction (PyMuPDF words → line spans) and applies pattern lists for SSN, EMAIL, PHONE, ACCOUNT_NUMBER (including alphanumeric `ACCT`/`ACCOUNT`/`ACC` variants), MEDICAL_TERM, plus a two-word Title-Cased NAME heuristic. Coordinates are resolved back to PDF rectangles.
- **Identity & reconciliation**: each candidate has an identity of `(document_id, page_number, category, matched_text, x0, y0, x1, y1)`. `reconcile_candidates()` **upserts** by identity, so repeated `detect` calls produce `candidates_created=0, candidates_skipped=N` and never duplicate. Existing `approved`/`applied` candidates are never deleted.
- **Approval**: a `RedactionApproval` (1:1) records approver, timestamps, and a verification struct.
- **Application**: `apply_redactions` redacts the source PDF by rectangle and writes a processed PDF; verification re-scans the result to confirm the matched text is gone.
- **PII leakage prevention**: the delivered `manifest.json` masks `matched_text` as `***` while preserving category/page/approver/verification; final artifacts are scanned to be free of seeded PII in tests and live QA.

## 7. Privilege Architecture

- `POST/GET /api/privilege/{packet_id}/{document_id}` marks a document `privileged` / `not_privileged` / `pending` with `reason`, `category`, and `reviewer`.
- `PATCH` overrides an existing decision.
- Every write first verifies `document.packet_id == packet_id` (UUID-to-UUID comparison). A cross-packet or missing document returns `404` (this was the C-1 regression).
- `/api/privilege/{packet_id}/log` returns the privileged subset with Bates ranges and categories for the privilege log.
- `ManifestEntry.privilege_status` / `privilege_category` / `privilege_reason` are populated at build time from the decision.
- Audit events `privilege_marked` carry `metadata.action` of `created` or `updated`.

## 8. Bates Architecture

- Assignment is contiguous across the packet, starting at `bates_start_number` and incrementing per page across documents in `display_order`.
- `bates_start_number` is validated `>= 0`; `bates_padding >= 1` (create + update) — negative/zero values are rejected at the schema layer.
- Numbers are auto-assigned on upload and **auto-re-reassigned on reorder, delete, or manual reassign** (contiguity is invariant). Each reassignment emits a `bates_assigned` audit event with `count` / `bates_start` / `bates_end`.
- `bates_label` is stamped onto cover sheets and the final packet via PyMuPDF.

## 9. Packet Build Pipeline

`exports.build` (→ `PacketBuilderService.build_packet`):

1. Load packet + documents in `display_order`.
2. Ensure each document has a processed (redacted, where applicable) PDF; reuse cached working artifacts when present.
3. Assign/confirm Bates for the packet (`BatesAssignmentService`).
4. For each document, stamp Bates labels onto pages, prepend a cover sheet (`EX-<letter>`), and append to the final writer.
5. Build the exhibit index PDF and the privilege log PDF.
6. Write `manifest.json` with SHA-256 for `final_packet.pdf`, each exhibit, each manifest entry, and the source processed file.
7. Run `_run_validation` (re-checks manifest SHAs against actual files).
8. Persist a `Manifest` + `ManifestEntry` rows, emit a `packet_built` audit event, commit.

Rebuilds delete the existing manifest/working output and replace it. See the README caveat about per-cover `Generated:` timestamps, which means rebuild byte output is not bit-stable but is always manifest-consistent.

## 10. Manifest and Integrity

- `manifest.json` (and the DB `Manifest` / `ManifestEntry` rows) holds packet-level totals, the Bates range, and per-entry SHA-256s.
- At build time the builder **re-computes** `final_packet_sha256` and compares it to the value it just wrote — a mismatch appends a "Final packet checksum mismatch" validation error.
- The delivered `manifest.json` does not expose raw `matched_text` for applied redactions (masked as `***`), so the integrity record contains no recoverable PII.

## 11. SuperDocs Integration

Adapter architecture (port/adapter): the application depends on `SuperDocsPort` (an interface) which is implemented by `SuperDocsRESTAdapter`. Business logic never imports SuperDocs SDKs directly.

```
Application (review router / integration service)
   ��  calls
SuperDocsPort (interface)
   ��  implemented by
SuperDocsRESTAdapter (HTTP + tenacity retries, bearer key from Settings)
   ��
SuperDocs REST API
```

- The API key (`SUPERDOCS_API_KEY`) lives only in `Settings` (loaded from `.env`) and is sent solely as an HTTP bearer header to SuperDocs. No endpoint returns it.
- **Session lifecycle**: a document is uploaded to SuperDocs on its first AI request; `superdocs_session_id` / `superdocs_document_id` are persisted so subsequent requests reuse the session (verified live — re-analyze does not re-upload).
- **Polling** drives status: `awaiting_approval` marks documents `waiting_review` and surfaces proposed changes; `completed` marks the document `completed`; `failed` routes to the AI failure path.
- **Error mapping** (`_translate_superdocs_error`): upstream 4xx → same code with a generic message, 5xx → 502, `httpx` timeouts/network errors → 504, other → 500. Provider bodies and keys are never leaked.
- **Failure recovery**: if analysis cannot start, the document is reverted to `completed` and an `ai_analysis_failed` audit event is recorded, so the document is never left stuck in `ai_analysis`.

## 12. Audit Architecture

Every lifecycle event is stored as an `AuditEvent` row (`event_type`, `user_id`, `event_metadata` JSON, `packet_id`, optional `document_id`, timestamp). `event_metadata` is persisted via the correct SQLAlchemy mapped column (`event_metadata`), so metadata is never silently NULL.

Events recorded include: `packet_created`, `packet_updated`, `packet_deleted`, `upload`, `upload_failed`, `processing_started`, `processing_completed`, `bates_assigned`, `privilege_marked` (with `action` created/updated), `redaction_proposed`, `redaction_approved`, `redaction_applied`, `redaction_verified`, `packet_validated`, `packet_built`, `ai_analysis_started`, `ai_analysis_completed`, `ai_analysis_failed`, `document_reordered`, `change_approved`, `change_rejected`.

Because `audit_events.packet_id` uses `SET NULL` on packet deletion, audit history is retained with the packet_id nulled out, while the `packet_deleted` event itself preserves the packet name/count in its metadata.

## 13. Storage Architecture

Files are organized under `STORAGE_ROOT` (configurable, defaults to `./storage`):

- `originals/<sha256>.<ext>` — the original uploaded bytes (content-addressed; duplicate uploads by content are detected here).
- `processed/<sha256>.pdf` — normalized PDF (DOCX/images converted).
- `working/<sha256>_redacted.pdf`, `<sha256>_stamped.pdf` — transient build artifacts.
- `final/<packet_id>/` — the shipped output: `final_packet.pdf`, `exhibit_index.pdf`, `privilege_log.pdf`, `exhibits/EX-*.pdf`, `manifest.json`.

Cleanup is **reference-aware**: `cleanup_unreferenced_original` only deletes an original once no `Document` references its SHA, and a failed upload computes the SHA of the already-buffered bytes and removes the staged file synchronously, leaving no orphan.

## 14. Frontend Architecture

- **React 18 + TypeScript** rendered via Vite.
- **Components**: thin presentational components plus a small hand-rolled `ui/` set (Button, Tabs, Toast) using `clsx` and Tailwind. Layout is a three-panel `PacketWorkspace` (documents list → document detail → redaction/privilege/review panels).
- **Services**: one Axios-based service module per backend resource (`packets`, `documents`, `bates`, `redactions`, `privilege`, `exports`, `review`, `processing`, `search`, `audit`).
- **Hooks**: React hooks wrap each service for data fetching and mutation (React Query for caching).
- **Types**: `src/types/api.ts` models the API payloads shared with the backend.
- State is local to hooks + React Query; there is no global store beyond the minimal `useToast` hook.

## 15. Error Handling

- **Validation**: Pydantic schema validation returns `422` for bad input (e.g., invalid UUID, negative Bates start).
- **4xx**: missing/misrouted resources return controlled `404`/`400` (e.g., wrong-packet privilege, non-approved apply, reason required).
- **SuperDocs errors**: translated per §11 — never leak provider bodies or keys.
- **Failed processing**: documents reach `failed` with an explanatory `processing_error` and `last_completed_step`; the upload itself rolls back so no partial files persist.
- **No stuck state**: failed AI analysis reverts the document to `completed`.

## 16. Security Boundaries

- API key is server-side only (`Settings` from `.env`), sent only as a bearer header to SuperDocs, and never returned by any endpoint.
- `.env`, `storage/`, caches, and build output are gitignored.
- Upload validation checks MIME type and PDF content sanity before persistence.
- Privilege decisions validate that the document belongs to the request's packet (UUID-to-UUID), preventing cross-packet access.
- PII handling: redaction candidates carry coordinates + matched text server-side; the delivered `manifest.json` masks matched text; all final artifacts are scanned to be free of seeded PII.
- SHA-256 manifest enables independent integrity verification of exported packets.

## 17. Testing Architecture

- **Unit tests**: domain, services (redaction detection, Bates, ingestion, packet builder, SuperDocs adapter + integration — adapter mocked). 69 pre-existing + new cases.
- **API-level tests**: exercise the real FastAPI routers through an `ASGITransport` client against an isolated PostgreSQL test DB + temp `STORAGE_ROOT`, with the SuperDocs service dependency overridden to a mocked adapter. 56 tests across `test_api_privilege`, `test_api_redactions`, `test_api_uploads`, `test_api_audit_events`, `test_api_pipeline_pii`, `test_api_review`.
- **H-1 unit suite**: 25 parametrized detection tests for account-number patterns and false-positive guards.
- **Live E2E**: `live_e2e_phase13.py` runs the full workflow against a running server with the real SuperDocs API.

Final verified numbers:

- Backend: **150 passed**
- Frontend unit (Vitest): **7 passed**
- TypeScript: `tsc --noEmit` **clean**
- Production build: **succeeds**
- Live E2E: **112/112 passed** (real SuperDocs)

## 18. Design Decisions / Why We Built It This Way

- **FastAPI** — lightweight, typed, async, automatic OpenAPI and input validation.
- **PostgreSQL + SQLAlchemy** — relational integrity for the packet/document/page/Bates/privilege graph; async sessions for concurrent uploads.
- **Alembic** — schema evolution scaffold alongside `create_all` for tests.
- **PyMuPDF / pypdf / pdfplumber** — mature, dependency-light PDF tooling for text extraction, rendering, and assembly.
- **React + TypeScript + Vite** — type-safe, fast-iter frontend workspace.
- **SuperDocs adapter (port/adapter)** — isolates the external provider dependency so business logic stays provider-independent and fully mockable in tests.
- **File storage** — documents and PDF artifacts are binary/large and do not belong inside relational rows.
- **Idempotent candidate reconciliation** — makes re-detection safe and cheap and prevents phantom duplicates in a legal workflow.
- **Audit events** — legal-document workflows require traceability of who did what, when.
- **SHA-256 manifest** — exported-packet integrity can be independently verified by re-hashing files.
- **Masked matched text in manifest** — preserves the redaction audit trail in the deliverable without re-introducing the redacted PII.

## 19. Operational Considerations

- Start dependencies: `docker compose up -d` (PostgreSQL). LibreOffice and Tesseract should be installed on the host for full DOCX/OCR support.
- Run the API from `backend/`: `uvicorn app.main:app --port 8000`.
- Run the frontend from `frontend/`: `npm run dev`.
- `STORAGE_ROOT` controls the artifact tree; ensure it is writable by the server process and excluded from backups of source-of-truth data.
- The server does not require Redis (background work uses FastAPI `BackgroundTasks`).

## 20. Future Improvements

- Replace per-cover `Generated:` timestamps with a build identifier if bit-stable rebuilds are ever required.
- Add ESLint configuration (or remove the dead `lint` script) to enable static frontend linting.
- Optionally wire a real background job queue if processing volume exceeds `BackgroundTasks`.