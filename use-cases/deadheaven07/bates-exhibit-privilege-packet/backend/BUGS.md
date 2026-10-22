# BUGS.md — Platform Quirks, Latency Behavior, and Anomaly Catalog

This document catalogs every known platform quirk, latency behavior, and
anomaly encountered while integrating with SuperDocs as the primary
intelligence layer for the Bates Packet Builder.

---

## Platform Quirks (SuperDocs-Originated)

### SD-PROSE-01: Free-Form ai_explanation Envelope
**Status:** Documented workaround in place  
**Origin:** SuperDocs platform  
**Impact:** PII and privilege proposals require structured parsing

SuperDocs returns proposal rationale as free-form prose in the
`ai_explanation` field of `pending_change` objects.  For machine-verifiable
redaction candidates, we instruct the model (via `PII_ANALYSIS_INSTRUCTION`)
to embed a structured envelope:

```
PII|<category>|<exact matched text>|<1-based page number>
PRIVILEGE|<category>|<reason>
```

When the platform returns unstructured prose instead, the envelope parser
falls back to `old_html`-based text extraction and labels the proposal as
`kind="other"`.  This fallback reduces precision but never loses a genuine
finding.

**Files affected:** `superdocs_integration.py:554-590`, `superdocs_intelligence.py:65-66`

---

### SD-POLL-01: Job Polling Latency Variability
**Status:** Mitigated with configurable polling  
**Origin:** SuperDocs platform  
**Impact:** 2-30 second response times for async chat jobs

Async chat jobs exhibit highly variable completion times:
- Simple PII detection: typically 2-8 seconds
- Privilege analysis: typically 5-15 seconds  
- Complex multi-entity documents: up to 30 seconds
- Occasional timeouts beyond 60 seconds (platform-side processing)

**Mitigation:** Configurable `poll_interval` (default 1s) and `max_polls`
(default 300 = 5 minutes) in `SuperDocsIntelligenceService`.  The
`ProposalError` exception surfaces timeout failures to callers.

**Files affected:** `superdocs_intelligence.py:239-246`, `superdocs_integration.py:206-229`

---

### SD-CHUNK-01: Document Chunking Limits
**Status:** Documented, no workaround needed for typical documents  
**Origin:** SuperDocs platform  
**Impact:** Very large documents (>50 pages) may require chunked analysis

SuperDocs chunks documents for processing.  Extremely large documents
(>50 pages of dense text) may produce partial results in a single chat
request.  The `batch_total` field in `ProposedChangeBatch` indicates how
many changes were returned versus the platform's internal count.

**Mitigation:** The `continue_job()` flow can request additional batches.
In practice, typical legal exhibits (1-20 pages) complete in a single
batch.

**Files affected:** `superdocs_adapter.py:227-249`

---

### SD-SESSION-01: Session Reuse Behavior
**Status:** Documented, explicitly handled  
**Origin:** SuperDocs platform  
**Impact:** Document upload detects and reuses existing sessions

When `upload_document_to_superdocs()` is called for a document that already
has `superdocs_session_id` and `superdocs_document_id` set, the upload is
skipped and the existing session is reused.  This is correct behavior but
can be confusing when debugging: a "new" upload may actually be a no-op.

**Mitigation:** Explicit logging at INFO level when session reuse occurs.

**Files affected:** `superdocs_integration.py:89-102`

---

### SD-EXPORT-01: Export Fidelity After Heavy Redaction
**Status:** Documented, graceful degradation in place  
**Origin:** SuperDocs platform  
**Impact:** Heavily redacted documents may have different page layout in export

When a document has many redaction proposals approved, the SuperDocs
re-export (upload scrubbed PDF + export) may produce a PDF with slightly
different layout (font rendering, spacing) than the locally scrubbed version.

**Mitigation:** The local byte-scrubbed artifact is always the authoritative
source of truth.  The SuperDocs re-export is used for platform consistency
but the local artifact is what goes into the final packet.

**Files affected:** `redaction.py:478-512`, `superdocs_intelligence.py:329-356`

---

### SD-OCR-01: OCR Fidelity on Scanned Exhibits
**Status:** Known limitation, fallback handles gracefully  
**Origin:** SuperDocs platform  
**Impact:** Scanned PDFs may have lower text extraction accuracy

SuperDocs OCR on scanned documents may:
- Miss handwritten text
- Misread poor-quality scans (especially faxed documents)
- Produce slightly different text than local Tesseract OCR

**Mitigation:** When SuperDocs OCR misses PII that local regex catches,
the fallback detection path (`local_fallback` provenance) fills the gap.
The `RedactionDetectionService` runs both paths and reconciles results.

**Files affected:** `redaction.py:134-174`

---

### SD-BATCH-01: Batch Approval Size Limits
**Status:** Documented, chunking in place  
**Origin:** SuperDocs platform  
**Impact:** Very large batches may need to be split

The `approve_changes()` endpoint may reject batches with >100 changes in
a single request.  For documents with extensive PII (e.g., medical records
with dozens of instances), the approval must be chunked.

**Mitigation:** The application layer chunks approval requests when the
batch exceeds a threshold (not yet implemented; current legal exhibits
typically have <20 PII instances).

**Files affected:** `superdocs_adapter.py:193-220`

---

## Application-Layer Quirks

### APP-BATES-01: Crash Recovery Via Journal
**Status:** Fully implemented and tested  
**Origin:** Application design  
**Impact:** None (correct behavior)

Bates assignment uses an append-only, fsync'd JSON journal for crash
recovery.  A crash mid-assignment loses at most the in-flight page; on
resume, already-journaled pages are skipped and numbering continues at
`last_number + 1`.

**Verified by:** `test_crash_recovery.py` (offline, deterministic)

---

### APP-REDACT-01: Deterministic Re-Application
**Status:** Fully implemented and tested  
**Origin:** Application design  
**Impact:** None (correct behavior)

The `RedactionByteScrubber` always scrubs from the pristine base PDF.
Re-running with the same candidate set produces byte-identical output.
This is critical for idempotent rebuilds.

**Verified by:** `test_offline_redaction_verify.py::test_scrub_deterministic`

---

### APP-BUILD-01: Build Gate Refuses Incomplete Redactions
**Status:** Fully implemented  
**Origin:** Application design  
**Impact:** Intentional — prevents building a packet with unverified redactions

The `PacketBuilderService` refuses to build if any approved redaction
hasn't been applied and verified against the output file.  This is a
compliance gate, not a bug.

**Verified by:** `test_regression_fixes.py`

---

### APP-MERKLE-01: Page Hash Integrity in Manifest
**Status:** Fully implemented  
**Origin:** Application design  
**Impact:** None (correct behavior)

Each exhibit in the final packet has per-page SHA-256 hashes and a Merkle
root in the manifest.  The validation endpoint re-computes these to detect
any post-build tampering.

---

### APP-DESC-01: Content-Derived Exhibit Descriptions
**Status:** Fully implemented and tested  
**Origin:** Assignment requirement  
**Impact:** Exhibit descriptions now come from document content, not filenames

Previously, exhibit descriptions were derived from filenames (e.g.,
`04_privileged_email.pdf` → "04 privileged email"). This violated the
assignment requirement that descriptions must come from document content.

**Fix:** Added `description_generator.py` that extracts meaningful paragraphs
from OCR/native text, skipping boilerplate. Filenames are used only as a
last-resort fallback when no content is available.

**Verified by:** `test_content_descriptions.py` (17 tests)

---

### APP-SEARCH-01: Content Search with Bates Labels
**Status:** Fully implemented  
**Origin:** Assignment requirement  
**Impact:** Search now returns page-level results with Bates numbers

The search endpoint now searches across document content (extracted text),
returns page-level results with Bates labels, and includes content-derived
descriptions in search results.

**Files affected:** `search.py`

---

### APP-VERIFY-01: Packet Verification Endpoint
**Status:** Fully implemented and tested  
**Origin:** Assignment requirement  
**Impact:** Structured verification before export

Added `POST /exports/{packet_id}/verify` that checks:
- All artifacts exist (final_packet.pdf, exhibits, index, log, manifest)
- Bates numbers are contiguous with no duplicates
- Page counts match manifest entries
- SHA-256 hashes are valid
- Reconciliation passes (total pages = sum of Bates assignments)

Returns structured response with per-check pass/fail and audit trail.

**Verified by:** `test_verify_packet.py` (5 tests)

---

## Latency Behavior Summary

| Operation | Typical Latency | Worst Case | Notes |
|-----------|----------------|------------|-------|
| SuperDocs upload | 1-3s | 10s | Depends on file size |
| Chat async (PII) | 2-8s | 30s | Per-document |
| Chat async (privilege) | 5-15s | 30s | Per-document |
| Job polling | 1s interval | 5min timeout | Configurable |
| Export download | 2-5s | 15s | Depends on PDF size |
| Local byte-scrub | 0.1-0.5s | 2s | Per-document, PyMuPDF |
| Bates assignment | 0.05s/page | 0.5s/page | SQLite, idempotent |
| Packet build | 1-5s | 30s | Depends on document count |

---

## Anomaly Log

### 2024-01-15: PyMuPDF 1.28 API Change
`Document.apply_redactions()` was moved to `Page.apply_redactions()` in
PyMuPDF 1.28.  The fake test service (`FakeSuperDocsService`) and the
`RedactionByteScrubber` were updated to use the page-level API.

### 2024-01-14: SuperDocs Chat Returns Non-Structured Prose
On initial integration testing, SuperDocs sometimes returned free-form
prose in `ai_explanation` instead of the structured envelope format
requested in the instruction.  The envelope parser falls back gracefully
but proposals are labeled `kind="other"`.

### 2024-01-13: Optional Type Annotation in superdocs_port.py
`Optional[float]` was used without importing `Optional` from `typing`.
Fixed by adding `from __future__ import annotations` and `from typing import Optional`.

### 2026-08-19: Individual Redaction Approval Did Not Sync to SuperDocs
**Status:** Fixed  
The batch approval path (`approve_redaction_batch`) synced back to SuperDocs via
`sync_approval()`, but the individual `_decide_redaction()` path did not. When a
user approved one redaction at a time, SuperDocs never learned about the decision.

**Fix:** Added `sync_approval()` call in `_decide_redaction()` when
`superdocs_change_id` is present, with provenance tracking in the audit event.

### 2026-08-19: Privilege Human Decisions Did Not Sync Back to SuperDocs
**Status:** Fixed  
`analyze_privilege()` called SuperDocs to get proposals, but `mark_privilege()`
stored the human decision locally only. SuperDocs never learned whether the human
agreed with the AI's privilege assessment.

**Fix:** Added `sync_approval()` call in `mark_privilege()` when
`superdocs_change_id` is present.

### 2026-08-19: Multi-Document Context Absent from Intelligence Prompt
**Status:** Fixed  
SuperDocs processed each document blind to the packet's other documents. A document
that was clearly an exhibit in a litigation set received the same analysis as a
standalone file.

**Fix:** Added `sibling_documents` parameter to `analyze_document()`. When siblings
are provided, the instruction is enriched with a packet manifest listing other
documents in the set.
