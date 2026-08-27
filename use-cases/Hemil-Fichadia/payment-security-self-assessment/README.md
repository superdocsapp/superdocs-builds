# Payment Security Self-Assessment

Payment Security Self-Assessment is a focused SuperDocs Task 2 use case for fintech and commerce teams. It accepts security evidence, extracts and classifies supported evidence, sends grounded facts to SuperDocs, and displays a generated payment-security self-assessment narrative for review.

It is not a PCI DSS certification engine, compliance guarantee, audit, or production document-management system.

Built as a SuperDocs Task 2 use case.

## Current flow

```text
Upload supported .txt evidence (or select fictional demo evidence)
→ process evidence in memory
→ inspect classified facts and provenance
→ upload a temporary HTML assessment template to SuperDocs
→ start an asynchronous grounded SuperDocs edit with `approval_mode: "ask_every_time"`
→ poll for proposed changes
→ human review of proposed changes
→ explicitly approve changes
→ obtain and validate the completed draft
→ export a real DOCX
```

The application creates a small in-memory HTML template for each generation. It does not persist uploaded files, evidence facts, templates, or generated drafts.

## Evidence ingestion

The current upload route accepts only plain-text evidence:

- `.txt` files with the `text/plain` content type
- Up to 3 files in one request
- Up to 100 KB per file

`/api/evidence` reads the files in memory, extracts qualifying lines, and returns the extracted facts to the browser. PDF and DOCX files are not supported.

For local inspection, the UI also includes **Use fictional demo evidence**, which loads the synthetic Meridian Payments corpus. It is clearly fictional and is not uploaded or persisted.

## Evidence model and classification

Each `EvidenceFact` retains:

- a stable fact ID
- category and status
- the original statement
- source document ID and source file name
- an optional source reference (uploaded text uses `Line N`)

The current classifier is intentionally deterministic and phrase/pattern based. It supports these categories:

- Authentication
- Access Control
- Encryption
- Logging & Monitoring
- Incident Response

Each fact has exactly one status:

| Status | Meaning |
| --- | --- |
| `IMPLEMENTED` | The supplied evidence supports a current control. |
| `PLANNED` | The supplied evidence describes future work; it must not be narrated as current. |
| `UNKNOWN` | The supplied evidence does not establish the control either way. |

Lack of evidence is not treated as proof that a control does not exist. Vague or arbitrary prose may not match the current deterministic patterns and can produce no fact; extracted facts should be inspected before generation.

## Grounding and safety behavior

Before generation, the assessment API validates the submitted fact shape and verifies that every fact still matches the server-side deterministic classifier. The SuperDocs instruction serializes each fact with its status and source information.

The generated draft is deterministically checked before display. Current safeguards include:

- Planned controls must not become implemented claims.
- The regression case is explicit: administrator MFA may be current, while workforce-wide MFA remains planned for Q4 2026.
- `UNKNOWN` controls must be narrated as limits of the supplied or available evidence.
- Obvious unsupported negative transformations of an `UNKNOWN` control, such as “not implemented” or “not established,” can be rejected.

These are focused, deterministic safeguards, not broad natural-language verification or a compliance determination.

## Prompt-injection boundary

Uploaded text is treated as untrusted evidence data. The application extracts it as text; it is not executed. The instruction sent to SuperDocs explicitly labels the serialized evidence block as quoted, untrusted data and directs SuperDocs not to follow instructions embedded in evidence statements.

This is a current input-handling safeguard, not a claim of comprehensive prompt-injection immunity.

## SuperDocs integration and approval

The browser calls local Next.js routes only. `SUPERDOCS_API_KEY` is loaded and used only in the server-side SuperDocs client; it is not sent to the browser.

For generation, `/api/assessment` uploads a minimal HTML template to `POST /v1/documents/upload`, then starts an asynchronous human-in-the-loop edit:

```text
POST https://api.superdocs.app/v1/chat/async
```

The server sends `approval_mode: "ask_every_time"`, polls `GET /v1/jobs/{job_id}` for proposed changes, and never auto-approves them. The browser receives an opaque, in-memory workflow ID; the server retains the SuperDocs session and job IDs only for the lifetime of the running server.

The human approval action calls `POST /v1/chat/{session_id}/approve` server-side. Once that job completes and the grounded draft passes validation, `GET /api/assessment/{workflowId}/export` proxies SuperDocs `POST /v1/documents/export` as a downloadable DOCX file. SuperDocs may retain its uploaded document/session according to its API lifecycle; this application itself has no database or restart-safe workflow persistence.

## Review flow

Users can inspect extracted evidence facts, grouped by category and status, before generation. Proposed changes are shown in sandboxed previews and are clearly marked as awaiting human approval. The completed draft is shown only after approval succeeds.

Export remains disabled until approval succeeds.

## Architecture

```text
apps/web
  ├─ upload/process and review UI
  ├─ /api/evidence
  └─ /api/assessment
       ↓
packages/evidence → deterministic classification
       ↓
packages/shared → EvidenceFact types and request validation
       ↓
server-side SuperDocs client → upload → async chat → approve → export
       ↓
grounded generated HTML → sandboxed draft review
```

This is a pnpm workspace managed by Turborepo. The Next.js App Router application is in `apps/web`; reusable types are in `packages/shared`; evidence extraction, classification, grouping, filtering, and synthetic demo data are in `packages/evidence`.

## Tests

The test suites run offline and do not require a SuperDocs API key. They cover:

- separation of implemented, planned, and unknown facts
- the administrator-MFA/current versus workforce-MFA/planned regression
- the 15-line mixed evidence regression corpus
- supported and unsupported uploads, including file-count and file-size limits
- prompt-like uploaded text remaining data rather than instructions
- SuperDocs upload, async job, approval, and export request/response parsing
- generated-draft grounding checks, including UNKNOWN evidence-limitation wording and negative-claim rejection

## Setup

Requirements: Node.js 20.9 or later and pnpm 10.28.2.

```bash
cd use-cases/Hemil-Fichadia/payment-security-self-assessment
pnpm install
cp .env.example .env
```

Set the placeholder in the workspace-root `.env` file:

```dotenv
SUPERDOCS_API_KEY=your-superdocs-api-key
```

The key is required only for live assessment generation. Keep `.env` local: it is ignored by Git. Never commit a real key.

## Run and validate

```bash
pnpm dev
```

Open [http://localhost:3000](http://localhost:3000).

```bash
pnpm lint
pnpm typecheck
pnpm test
pnpm build
```

To serve a production build after `pnpm build`:

```bash
pnpm --filter @payment-security-self-assessment/web start
```

## Known limitations

- No dedicated SuperDocs search integration
- `.txt` / `text/plain` ingestion only; no PDF or DOCX ingestion
- Deterministic phrase-based classification only; it is not semantic AI classification
- No persistence of uploads, facts, drafts, or assessments
- No application authentication
- Not a PCI DSS certification, compliance guarantee, or audit engine
