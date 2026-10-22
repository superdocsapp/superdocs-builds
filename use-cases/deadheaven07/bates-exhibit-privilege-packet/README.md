# Bates Exhibit & Privilege Packet Builder

A production-grade legal e-discovery tool that ingests court filings and exhibits, applies deterministic Bates numbering, detects and redacts PII, marks privileges, and exports a reconciled exhibit packet with a tamper-evident manifest.

## Overview

Law firms and litigation-support teams produce exhibit packets for production and disclosure. A packet is a **Bates-stamped**, **privilege-logged**, **redacted** PDF bundle whose integrity can be independently verified from a manifest of SHA-256 hashes. This system makes the full workflow reproducible and auditable: from raw upload through to a final, PII-free, privilege-filtered PDF packet.

## Key Capabilities

- **Packet management** — create, rename, list, reorder, and delete exhibit packets.
- **Document ingestion** — accepts PDF, DOCX (via LibreOffice), scanned PDFs and images (via PDF images), with OCR fallback.
- **Bates numbering** — contiguous assignment per page, auto on upload, manual assign, and automatic re-stamping on reorder.
- **PII redaction** — detects SSNs, phone numbers, emails, names, account numbers (including alphanumeric `ACC-8821-4433`-style values) and medical terms.
- **Redaction workflow** — detect → propose → review/approve → apply → verify that redacted text is actually gone.
- **Privilege marking** — mark documents `privileged` / `not_privileged`, with reason/category, override, and a machine + human-readable privilege log.
- **AI review** — delegates to the SuperDocs API for drafting/review; sessions are reused per document and failures leave the document in a recoverable state.
- **Packet build** — cover sheets, stamps, exhibit-index PDF, privilege log, and a `manifest.json` with SHA-256 hashes for the final packet, every exhibit, and every source entry.
- **Validation & integrity** — validation pass before build; manifest SHAs are re-checked at build time.
- **Export** — final packet, per-exhibit PDFs, privilege log, and manifest for download.
- **Audit trail** — every significant lifecycle event (upload, processing, Bates, redaction, privilege, validate, build, AI) is recorded with metadata.
- **Reference-aware storage cleanup** — original/stamped/redacted files are deleted only when no document references them; uploads roll back on failure so no orphan files are left.

## Architecture

- **Backend:** FastAPI + SQLAlchemy (async, PostgreSQL), organized into API / services / domain / workers / storage / SuperDocs adapter layers. Alembic migrations under `backend/alembic`.
- **Frontend:** React + TypeScript, built with Vite, tested with Vitest, typed with `tsc`.
- **External:** PostgreSQL for relational state and audit; file storage for artifacts; the SuperDocs API for AI review (key kept server-side only).

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full architecture.

## Core Workflow

```
Upload → Validate → Process (OCR/text) → Bates assignment
    → Detect PII → Review/Approve → Apply redactions → Verify redaction
    → Privilege review → AI review (SuperDocs, session reuse)
    → Validate → Build (covers + stamps + index + privilege log + manifest)
    → Manifest/SHA verification → Export
```

## Tech Stack

| Technology                | Purpose            | Why                                             |
| ------------------------- | ------------------ | ----------------------------------------------- |
| Python 3.11+              | Backend runtime    | Ecosystem for PDF/PDF tooling, FastAPI async    |
| FastAPI                   | API framework      | Typed, async, automatic OpenAPI + validation    |
| SQLAlchemy 2.0            | ORM/persistence    | Async sessions, transactional workflows         |
| PostgreSQL                | Database           | Relational integrity for packet/document/state  |
| Alembic                   | Migrations         | Schema evolution                                |
| PyMuPDF (fitz)            | PDF rendering/text | Redaction detection, cover sheets, verification |
| pypdf                     | PDF assembly       | Final packet stamping and assembly              |
| pdfplumber                | Text extraction    | PII detection on text layers                    |
| pdf2image + Tesseract     | OCR/imaging        | Scanned-image text extraction                   |
| python-docx + LibreOffice | DOCX → PDF         | Convert Word exhibits                           |
| python-magic              | MIME detection     | Upload type validation                          |
| Pillow                    | Image handling     | Image-based PDF ingestion                       |
| httpx + tenacity          | SuperDocs client   | HTTP + retries for the external AI API          |
| React 18                  | Frontend UI        | Interactive workspace                           |
| TypeScript                | Frontend typing    | Type-safe API integration                       |
| Vite                      | Frontend build/dev | Fast dev server + build                         |
| Vitest                    | Frontend tests     | Unit/component test runner                      |
| Tailwind CSS              | Styling            | Utility CSS                                     |
| @tanstack/react-query     | Data fetching      | Server state caching                            |
| Zustand                   | State management   | Lightweight global store                        |
| SuperDocs API             | AI review          | External provider for drafting/analysis         |

## Project Structure

```
bates-exhibit-privilege-packet/
├── backend/
│   ├── app/
│   │   ├── api/        # FastAPI routers (route handlers, validation)
│   │   ├── services/   # application: ingestion, redaction, bates, packet builder, SuperDocs adapter, storage
│   │   ├── workers/    # background processing (document processing retry path)
│   │   ├── domain/     # SQLAlchemy ORM models + enums
│   │   ├── tests/      # pytest unit + API-level tests
│   │   ├── main.py     # app factory, CORS, router registration, lifespan
│   │   ├── config.py   # Settings (pydantic-settings)
│   │   ├── database.py # engine/session, async init
│   │   └── time.py     # utc_now
│   ├── alembic/        # migrations
│   ├── live_e2e_phase13.py   # repeatable live end-to-end QA script
│   ├── pyproject.toml
│   └── .env            # (gitignored) real SUPERDOCS_API_KEY + DB URL
├── frontend/
│   └── src/            # React components, hooks, services, types
├── docker-compose.yml  # PostgreSQL
├── .env.example        # environment variable template (no secrets)
��── README.md / ARCHITECTURE.md
```

## Getting Started

### Prerequisites

- Python 3.11+
- Node.js 18+
- PostgreSQL 16 (the `docker-compose.yml` starts one)
- **Recommended for full functionality:** LibreOffice (`libreoffice`) and Tesseract (`tesseract`) on `PATH`. Without them, DOCX conversion and OCR are disabled — document processing still works for text-based PDFs (see [Known Environment Requirements](#known-environment-requirements)).
- A SuperDocs API key (set `SUPERDOCS_API_KEY`).

### Backend

```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # then fill in SECRET values
# start PostgreSQL (one terminal)
docker compose up -d
# start the API
uvicorn app.main:app --reload --port 8000
```

The API is then available at `http://localhost:8000` (OpenAPI at `/docs`).

### Frontend

```bash
cd frontend
npm install
npm run dev    # → http://localhost:5173
```

### Environment Variables

Copy `.env.example` (backend). All secrets live only in `.env` (gitignored):

| Variable                                                     | Required        | Default                         | Description                                                  |
| ------------------------------------------------------------ | --------------- | ------------------------------- | ------------------------------------------------------------ |
| `SUPERDOCS_API_KEY`                                          | yes (AI review) | `your-key-here`                 | SuperDocs API key — server-side only, never sent to clients. |
| `SUPERDOCS_BASE_URL`                                         | no              | `https://api.superdocs.app`     | SuperDocs endpoint.                                          |
| `DATABASE_URL`                                               | yes             | —                               | PostgreSQL connection string.                                |
| `STORAGE_ROOT`                                               | no              | `./storage`                     | Root for original/processed/working/final files.             |
| `ORIGINALS_DIR`, `PROCESSED_DIR`, `WORKING_DIR`, `FINAL_DIR` | no              | `originals`, …                  | Subdirectory names.                                          |
| `TESSERACT_CMD`, `TESSERACT_LANG`                            | no              | `tesseract`, `eng`              | OCR configuration.                                           |
| `BATES_PREFIX`, `BATES_START_NUMBER`, `BATES_PADDING`        | no              | `CASE-`/`1`/`6`                 | Defaults.                                                    |
| `APP_HOST`, `APP_PORT`, `DEBUG`, `LOG_LEVEL`                 | no              | `0.0.0.0`/`8000`/`false`/`INFO` | Runtime.                                                     |

## Testing

Final verified numbers:

- Backend: `pytest -q` → **150 passed**, 7 warnings
- Frontend unit: `npx vitest run` → **7 passed**
- TypeScript: `npx tsc --noEmit` → **clean**
- Production build: `npm run build` → **succeeds**
- Live E2E: `python live_e2e_phase13.py` → **112/112 checks passed** against the running server + real SuperDocs

### Local test database

Tests run against `postgresql+asyncpg://postgres:postgres@localhost:5432/bates_packet_test`. Start a test database:

```bash
docker run -d --name bates-pg-test \
  -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=bates_packet_test \
  -p 5432:5432 postgres:16-alpine
```

## Security

- The SuperDocs API key is loaded from the server `.env` only and is **never** returned by any endpoint or exposed to the frontend.
- `.env`, `storage/`, `*.pdf`, `*.docx`, caches, and build output are gitignored.
- Upload validation checks MIME type and file content, and corrupt files are rejected before persistence.
- A failed upload rolls back all files (no orphan originals left on disk).
- `manifest.json` masks applied-redaction text (`matched_text` → `***`) so raw PII is not present in any delivered artifact.
- All final artifacts (final packet, covers, exhibit index, privilege log, exhibits, manifest) are scanned to be free of seeded PII.
- Privilege decisions validate the document belongs to the request's packet (UUID-to-UUID comparison), preventing cross-packet access.
- SuperDocs provider errors are translated to generic, controlled messages; raw provider bodies and keys are never surfaced.
- SHA-256 hashes in the manifest allow independent verification of exported packet integrity.

## Reliability / Idempotency

- **Redaction detection** is idempotent — repeated `detect` calls upsert candidates by identity and never duplicate, never delete approved/applied candidates.
- **Rebuilt packets** replace artifacts safely and re-verify manifest hashes.
- **Duplicate uploads** of identical content are rejected with `409`.
- **File deletion** is reference-aware — a shared source file is removed only when the last referencing document is deleted.
- **SuperDocs session reuse** — re-running analysis on a document reuses its existing session instead of re-uploading.
- **Failed AI analysis** reverts the document to `completed` so it is never stuck in `ai_analysis`.

## Known Environment Requirements

- **LibreOffice** (`libreoffice`): used to convert DOCX → PDF. If absent, DOCX uploads are marked `FAILED` with `"LibreOffice unavailable: cannot convert DOCX to PDF"` and are not processed further.
- **Tesseract** (`tesseract`): used for OCR of scanned-image PDFs and images. If absent, OCR is skipped and documents are processed from any extractable text layer.

Without both tools, the system still fully processes text-based PDF exhibits end to end.

## QA / Verification

A repeatable live end-to-end QA is provided at `backend/live_e2e_phase13.py`. It runs the full workflow against a running backend (with a real SuperDocs key), verifying upload, Bates, privilege (incl. the wrong-packet 404 regression), PII detection (incl. `ACC-8821-4433`-style accounts), idempotent re-detection, approve/apply, PII-free artifact generation, manifest SHA verification, idempotent rebuild, corrupt-upload orphan prevention, invalid-UUID 422s, real SuperDocs AI with session reuse, audit-trail completeness, and full storage/DB cleanup on packet deletion.

## Verification Status

| Check            | Status                    |
| ---------------- | ------------------------- |
| Backend tests    | 150 passed                |
| Frontend tests   | 7 passed                  |
| TypeScript       | clean                     |
| Production build | succeeds                  |
| Live E2E         | 112/112 passed            |
| Security         | verified                  |
| Storage cleanup  | reference-aware           |
| Database cleanup | cascades + SET NULL audit |

**Final status: READY FOR PR**
