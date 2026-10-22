# Bates Exhibit & Privilege-Log Packet Builder

> **SuperDocs is the document substrate and the AI review loop.  
> Bates Packet Builder is the vertical compliance and packaging layer on top of it.**

A production-grade legal e-discovery tool that produces court-ready document
packets with Bates stamping, privilege logging, PII redaction, and
mathematical compliance proofs.

---

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full system design.

### Core Pipeline

```
Upload → Process → AI Review (SuperDocs) → Human Approval → Byte-Scrub
→ Reimport to SuperDocs → Bates Stamp → Assemble → Reconcile → Deliver
```

**SuperDocs is the primary intelligence layer.** PII detection, privilege
analysis, and redaction proposals flow through the SuperDocs async chat API
with `approval_mode="ask_every_time"` — every suggestion is a native
`pending_change` that a human reviewer must approve or reject before any
byte is modified.

The local regex/PyMuPDF engine is a **demoted fallback** used only when
SuperDocs is unavailable (no API key, network failure, or upstream error).
Every fallback proposal is explicitly labeled with `provenance="local_fallback"`.

### Compliance Invariants

| Invariant | Proof |
|-----------|-------|
| **Bates continuity** (zero gaps, zero double-stamping) | Append-only fsync'd journal + `ContinuityProof` |
| **Redaction verification** (text truly gone) | PyMuPDF text extraction confirms absence |
| **Rejection safety** (source unchanged) | `test_safety_rejection.py` proves byte-identical |
| **Deterministic rebuild** (idempotent) | Always scrub from pristine base PDF |
| **Page-count reconciliation** | `total_pages == sum(Bates ranges) + covers` |
| **Merkle integrity** | Per-page SHA-256 + Merkle root in manifest |

---

## Quick Start

```bash
cd backend

# Install dependencies
pip install -e ".[dev]"

# Run offline tests (no API key, no database)
pytest app/tests/test_offline_state_machine.py \
       app/tests/test_crash_recovery.py \
       app/tests/test_offline_bates_resume.py \
       app/tests/test_offline_redaction_verify.py \
       app/tests/test_safety_rejection.py \
       app/tests/test_evaluation.py \
       -v

# Run all tests (requires database)
pytest -v

# Lint and type check
ruff check app/
mypy --explicit-package-bases app/
```

---

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/packets` | POST | Create a new packet |
| `/api/documents/{packet_id}/upload` | POST | Upload a document |
| `/api/processing/{packet_id}/start` | POST | Start text extraction |
| `/api/review/{packet_id}/documents/{doc_id}/analyze` | POST | Run SuperDocs AI analysis |
| `/api/review/{packet_id}/documents/{doc_id}/approve` | POST | Approve a pending change |
| `/api/redactions/{packet_id}/detect/{doc_id}` | POST | Detect PII (SuperDocs primary) |
| `/api/redactions/{packet_id}/approve/{candidate_id}` | POST | Approve a redaction |
| `/api/redactions/{packet_id}/apply/{doc_id}` | POST | Apply approved redactions |
| `/api/privilege/{packet_id}/analyze` | POST | Analyze privilege (SuperDocs) |
| `/api/bates/{packet_id}/assign` | POST | Assign Bates numbers |
| `/api/exports/{packet_id}/build` | POST | Build final packet |
| `/api/bates/{packet_id}/continuity-proof` | GET | Prove Bates continuity |

---

## Testing Strategy

### Offline Tests (Primary Proof)

Tests that require **no API key, no database, and no network**:

| Test Suite | What It Proves |
|------------|----------------|
| `test_offline_state_machine.py` | Redaction state machine transitions |
| `test_crash_recovery.py` | Bates journal crash recovery + continuity |
| `test_offline_bates_resume.py` | Sequential numbering + resume |
| `test_offline_redaction_verify.py` | Byte-scrub + verify cycle |
| `test_safety_rejection.py` | Rejected redactions leave source unchanged |
| `test_evaluation.py` | Precision/recall/F1 against fixed corpus |

### Integration Tests (Secondary Verification)

| Test Suite | What It Tests |
|------------|---------------|
| `test_api_*.py` | API endpoint behavior |
| `test_superdocs_*.py` | SuperDocs adapter/integration |
| `test_api_pipeline_pii.py` | Full pipeline end-to-end |

### Evaluation Corpus

Pre-registered test documents with known ground truth:

```
corpus/
├── test_document_ssn_email.pdf      # SSN, email, phone, account, medical
├── test_document_privilege.pdf      # Attorney-client privilege language
├── test_document_edge_cases.pdf     # Invoice refs, dates, Bates labels
├── test_document_multipage.pdf      # Multi-page with PII on page 3
└── expected.yaml                    # Ground-truth definitions
```

---

## Platform Quirks

See [BUGS.md](BUGS.md) for a comprehensive catalog of SuperDocs platform
quirks, latency behavior, and anomalies encountered during integration.

---

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `SUPERDOCS_API_KEY` | `your-key-here` | SuperDocs API key |
| `SUPERDOCS_PRIMARY` | `true` | Enable SuperDocs as primary intelligence |
| `DATABASE_URL` | PostgreSQL | Database connection |
| `BATES_PREFIX` | `CASE-` | Default Bates prefix |
| `BATES_PADDING` | `6` | Zero-padding width |

### Court Profiles

Two pre-configured profiles in `config/court_rules.json`:
- **SDNY_FEDERAL**: Federal court formatting
- **CALIFORNIA_SUPERIOR**: California state court formatting

---

## License

MIT
