# Task 2 - Type 3 Build
## Invoice Anomaly Investigator

### Problem Statement
Accounts payable teams process large volumes of invoices under tight timelines. Manual review often misses high-risk anomalies such as duplicate submissions, amount mismatches, and suspicious vendor payment-detail changes. The result is preventable financial loss, delayed approvals, and weak audit trails.

Build an extension for SuperDocs that performs first-pass anomaly investigation for invoices, produces evidence-backed findings, and enforces a human decision gate before final export.

### Why This Is Useful For SuperDocs
SuperDocs already provides document upload, structured conversation, approval workflows, and exports. This extension adds a focused fraud/compliance layer that:
- Improves trust in document-driven financial workflows.
- Creates deterministic, reviewable investigation artifacts.
- Reuses existing SuperDocs interaction patterns (`upload`, `chat`, `approve`, `export`).

### Goal
Create a testable, offline-capable extension that:
- Ingests invoice documents and extracts key fields.
- Detects predefined anomaly classes deterministically.
- Explains findings with evidence suitable for audit review.
- Requires explicit reviewer approval decision before export.

### In Scope
- Invoice field extraction from text fixtures (invoice ID, vendor, dates, totals, line items, payment details).
- Deterministic anomaly checks:
  - Duplicate invoice ID detection.
  - Total mismatch between computed line-item sum and declared total.
  - Vendor payment-detail change against known baseline.
- Investigation run lifecycle with persisted states.
- Human decision states: `approved`, `rejected`, `needs_review`.
- Exportable investigation report (HTML minimum; optional DOCX/PDF in fixture implementation).
- Local test transport that supports idempotency and retry-safe behavior.

### Out of Scope
- Production fraud scoring models.
- OCR accuracy benchmarking.
- Multi-tenant auth/permissions.
- Real banking network verification.

### Inputs And Outputs
#### Inputs
- Invoice documents (fixture text/PDF converted text).
- Optional baseline/vendor registry for payment-detail comparison.

#### Outputs
- Structured anomaly findings with severity and evidence.
- Reviewer decision record and rationale.
- Investigation report artifact for audit archive.

### SuperDocs Contract Mapping
- `upload`: store normalized invoice snapshot and metadata.
- `chat`: answer reviewer questions about anomalies and supporting evidence.
- `approve`: capture final human decision with justification.
- `export`: generate immutable investigation packet.

### Functional Requirements
1. The system must create a content-addressed snapshot for each invoice ingestion.
2. The system must generate deterministic anomaly results for the same input.
3. The system must block export until a reviewer decision exists.
4. The system must persist run state transitions and decisions in durable storage.
5. The system must support idempotent operation retries after uncertain remote outcomes.

### Non-Functional Requirements
- Deterministic behavior in fixture mode.
- Fully offline testability.
- Clear auditability: each finding references source evidence.
- Small, understandable code surface for review.

### Acceptance Criteria
1. Given a duplicate invoice fixture, the system flags `duplicate_invoice_id`.
2. Given mismatched totals, the system flags `total_mismatch` with computed vs declared values.
3. Given changed vendor payment details, the system flags `payment_detail_change`.
4. Export request before decision returns a blocked/error state.
5. After `approve`, export succeeds and includes findings + decision trail.
6. Replaying the same upload with the same idempotency key does not create duplicate side effects.

### Suggested Test Slice
- Unit tests for parsing/extraction logic.
- Unit tests for each anomaly detector.
- Workflow tests for state transitions and export gate behavior.
- Transport tests for idempotency and retry semantics.
- Golden-output test for deterministic report body.

### Deliverable Definition (Fixture Build)
A complete fixture extension directory under `extensions/RSWDevian/invoice-anomaly-investigator/` containing:
- Problem definition (this file).
- Minimal implementation of core investigation flow.
- Automated tests proving deterministic anomaly detection and review gating.

### Stretch (Optional)
- Severity prioritization rules.
- Cross-document anomaly linking (same amount/date/vendor clusters).
- Optional REST/MCP adapter parity with other SuperDocs builds.
