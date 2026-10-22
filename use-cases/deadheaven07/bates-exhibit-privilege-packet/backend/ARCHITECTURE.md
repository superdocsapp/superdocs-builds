# Architecture

> **SuperDocs is the document substrate and the AI review loop.  
> Bates Packet Builder is the vertical compliance and packaging layer on top of it.**

---

## System Overview

```
┌──────────────────────────────────────────────────────────────────────┐
│                    SUPERDOCS PLATFORM (Document Substrate)           │
│                                                                     │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────────────────┐ │
│  │  Document    │  │  Async Chat  │  │  Proposed Changes Engine   │ │
│  │  Upload API  │  │  API         │  │  (pending_change objects)  │ │
│  │  (REST)      │  │  (ask_every  │  │  approval_mode:            │ │
│  │              │  │   _time)     │  │    ask_every_time          │ │
│  └──────┬───────┘  └──────┬───────┘  └────────────┬───────────────┘ │
│         │                 │                        │                 │
│         └─────────────────┼────────────────────────┘                 │
│                           │                                          │
│                    ┌──────▼──────┐                                    │
│                    │  Export API  │                                    │
│                    │  (PDF out)  │                                    │
│                    └──────┬──────┘                                    │
└───────────────────────────┼──────────────────────────────────────────┘
                            │
┌───────────────────────────▼──────────────────────────────────────────┐
│            BATES PACKET BUILDER (Compliance + Packaging)             │
│                                                                     │
│  ┌───────────────┐  ┌───────────────┐  ┌──────────────────────────┐ │
│  │ Intelligence  │  │  Redaction    │  │  Packet Assembly         │ │
│  │ Layer         │  │  Pipeline     │  │  (Bates stamp, covers,   │ │
│  │ (SuperDocs    │  │  (byte-scrub  │  │   index, privilege log,  │ │
│  │  primary,     │  │   + verify    │  │   manifest, reconcile)   │ │
│  │  fallback)    │  │   + reimport) │  │                          │ │
│  └───────────────┘  └───────────────┘  └──────────────────────────┘ │
│                                                                     │
│  ┌───────────────┐  ┌───────────────┐  ┌──────────────────────────┐ │
│  │  Bates        │  │  Court Rules  │  │  Storage Management      │ │
│  │  Assignment   │  │  Config       │  │  (reference-aware,       │ │
│  │  + Journal    │  │  (SDNY, CA)   │  │   path resolution)       │ │
│  └───────────────┘  └───────────────┘  └──────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Core Data Flow

```
1. UPLOAD        User uploads PDF → stored as original, SHA-256 hashed
                 ↓
2. PROCESS       Text extraction (PyMuPDF) + OCR fallback (Tesseract)
                 ↓
3. INTELLIGENCE  SuperDocs chat API (ask_every_time) → pending_changes
                 Fallback: local regex engine (when SuperDocs unavailable)
                 ↓
4. HUMAN REVIEW  Approve/reject each pending_change one-by-one or in batches
                 ↓
5. BYTE-SCRUB    PyMuPDF redact annotations from pristine base PDF
                 Verify: text truly gone from output
                 ↓
6. RE-IMPORT     Upload scrubbed PDF back to SuperDocs → export native doc
                 ↓
7. BATES STAMP   Sequential numbering via journal (crash-recoverable)
                 ↓
8. ASSEMBLE      Cover sheets + exhibits + index + privilege log
                 ↓
9. RECONCILE     Mathematical proof: total pages == sum(Bates ranges) + covers
                 ↓
10. DELIVER      Final packet PDF + manifest + Merkle root integrity
```

---

## Primary Intelligence Layer (SuperDocs)

### Why SuperDocs Is Primary

SuperDocs provides semantic understanding that regex cannot:
- **Contextual PII detection**: Distinguishes "SSN: 123-45-6789" from "Invoice INV-12345"
- **Privilege analysis**: Understands legal privilege language semantically
- **Structured proposals**: Each finding is a native `pending_change` requiring human approval
- **Platform consistency**: Final artifacts are native SuperDocs documents

### The ask_every_time Protocol

Every AI analysis uses `approval_mode="ask_every_time"`:

1. **SuperDocs proposes**: Chat API analyzes document, returns `pending_change` objects
2. **Human approves/rejects**: Each proposal is individually reviewed
3. **Application processes**: Approved proposals → byte-scrub → reimport to SuperDocs
4. **Platform stays consistent**: SuperDocs-side document reflects human decisions

This is NOT approve_all. Every single proposal requires explicit human action.

### Fallback Path (Demoted)

When SuperDocs is unavailable (no API key, network failure, upstream error):
- Local regex engine (`local_engine.py`, `fallback_detection.py`) provides detection
- Every proposal is labeled with `provenance="local_fallback"`
- The fallback is documented as intentionally simpler than SuperDocs
- The compliance workflow (Bates, redaction verification, packet build) remains fully operational offline

---

## Compliance Invariants

### 1. Bates Continuity (Zero Gaps, Zero Double-Stamping)

Every page in every document receives exactly one sequential Bates number.
The journal (`bates_journal.py`) provides:
- Append-only, fsync'd JSON log
- Crash recovery: resume from `last_number + 1`
- Mathematical proof: `ContinuityProof` validates gaps, duplicates, double-stamps

### 2. Redaction Verification (Text Truly Gone)

The build gate refuses to build if any APPLIED redaction's text is still
extractable from the redacted artifact. Verification uses PyMuPDF text
extraction to confirm absence.

### 3. Deterministic Re-Application

The `RedactionByteScrubber` always scrubs from the pristine base PDF.
Re-running with the same candidate set produces byte-identical output.
This is proven offline in `test_offline_redaction_verify.py`.

### 4. Rejection Safety (Source Unchanged)

When a reviewer rejects 100% of proposed redactions, the source files
remain bit-for-bit unchanged. Proven in `test_safety_rejection.py`.

### 5. Page-Count Reconciliation

Mathematical proof at build time:
```
Total Packet Pages == Sum(Exhibit Bates Ranges) + Number of Exhibits (covers)
```

### 6. Merkle Integrity

Per-page SHA-256 hashes + Merkle root in the manifest detect any post-build
tampering of exhibit PDFs.

---

## Module Reference

### Intelligence Layer
| Module | Role | Dependency |
|--------|------|------------|
| `superdocs_port.py` | Abstract interface + data classes | None (pure types) |
| `superdocs_adapter.py` | REST client with tenacity retry | httpx, tenacity |
| `superdocs_integration.py` | Orchestrates upload/chat/approval/export | SuperDocs REST |
| `superdocs_intelligence.py` | Primary intelligence (chat + ask_every_time) | SuperDocs REST |
| `local_engine.py` | **FALLBACK**: Regex PII/privilege detection | None (pure Python) |
| `fallback_detection.py` | **FALLBACK**: PyMuPDF + regex with coordinates | PyMuPDF |

### Redaction Pipeline
| Module | Role |
|--------|------|
| `redaction.py` | Detection service (SuperDocs primary, fallback secondary) + Application service (byte-scrub + verify + reimport) |
| `redaction_scrubber.py` | True byte-scrubbing via PyMuPDF redact annotations |
| `redaction_state.py` | Pure state machine (DB-free, offline-provable) |

### Compliance Engine
| Module | Role |
|--------|------|
| `bates_assignment.py` | Sequential Bates numbering with resume |
| `bates_journal.py` | Append-only fsync'd crash-recovery journal |
| `reconciliation.py` | Mathematical page-count proof |
| `court_rules.py` | Court-specific formatting profiles |
| `packet_builder.py` | Final PDF assembly + SuperDocs re-export |

### Storage
| Module | Role |
|--------|------|
| `storage.py` | Path helpers, reference-aware cleanup |
| `ingestion.py` | File validation, MIME detection, SHA-256 |

---

## Testing Strategy (Dual Evidence)

### Offline Tests (Primary Proof)
- State machine transitions (`test_offline_state_machine.py`)
- Bates resume and continuity (`test_crash_recovery.py`, `test_offline_bates_resume.py`)
- Redaction verification (`test_offline_redaction_verify.py`)
- Safety rejection (`test_safety_rejection.py`)
- Evaluation metrics (`test_evaluation.py`)

### Integration Tests (Secondary Verification)
- API endpoint tests (`test_api_*.py`)
- SuperDocs adapter/integration tests (`test_superdocs_*.py`)
- Full pipeline tests (`test_api_pipeline_pii.py`)

### Configuration
- All tests run with `pytest-asyncio` in `auto` mode
- Offline tests require no API key, no database, no network
- Live E2E tests (112 checks) are configured as secondary verification

---

## Configuration

### Court Rules (`config/court_rules.json`)
Two profiles: `SDNY_FEDERAL` and `CALIFORNIA_SUPERIORIOR`.

### Environment Variables
| Variable | Default | Description |
|----------|---------|-------------|
| `SUPERDOCS_API_KEY` | `your-key-here` | SuperDocs API key (placeholder = fallback mode) |
| `SUPERDOCS_PRIMARY` | `true` | Enable SuperDocs as primary intelligence layer |
| `DATABASE_URL` | PostgreSQL async | Database connection string |
| `BATES_PREFIX` | `CASE-` | Default Bates prefix |
| `BATES_START_NUMBER` | `1` | Default starting number |
| `BATES_PADDING` | `6` | Zero-padding width |

### Fallback Activation
SuperDocs is primary only when:
1. `SUPERDOCS_PRIMARY=true` (default)
2. A real API key is configured (not placeholder)

Otherwise, the local fallback path activates automatically with explicit `provenance="local_fallback"` labels.
