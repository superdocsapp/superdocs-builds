# PRD: Nursing Handoff & Transfer Packet Assembler (Task 2)

## 1. Product Vision & Strategy

### Vision Statement
Eliminate hand-assembled transfer packets that cause **patient safety incidents** by giving charge nurses and transfer coordinators a **structured, verified, export-gated packet builder** that produces receiving-unit-ready PDFs in minutes, not hours.

### Strategic Rationale
- **Clinical Impact**: Incomplete handoffs cause ~30% of adverse events (Joint Commission). Current process: 45-90 min manual assembly, error-prone.
- **SuperDocs Differentiator**: Our "edit in place + review mode + citation survival" maps perfectly to clinical documentation — every field traces to source.
- **Market Entry**: Healthcare is a high-trust, high-ACV vertical. This build demonstrates SuperDocs for regulated, safety-critical workflows.

### Target Users
| Persona | Role | Pain Point |
|---------|------|------------|
| **Charge Nurse (ICU/Step-down)** | Initiates transfer, owns clinical accuracy | "I'm pulling meds from 4 screens, orders from 2, notes from 3 — and the ambulance waits" |
| **Transfer Coordinator** | Logistics, receiving unit comms | "Receiving unit rejects packets missing isolation status or with unverified allergies" |
| **Receiving Unit Nurse** | Accepts patient, needs trust | "I need the packet in *our* order so I don't miss anything during sign-in" |

### Success Metrics
| Metric | Target | Measurement |
|--------|--------|-------------|
| **Packet assembly time** | ≤15 min (vs 45-90 manual) | Stopwatch study with 5 nurses |
| **High-risk field gate compliance** | 100% — export blocked until all confirmed | Automated test + user observation |
| **Med reconciliation flag rate** | ≥95% of true duplicates flagged | Synthetic test set with known duplicates |
| **Receiving unit acceptance** | Zero "missing section" rejections in pilot | Partner site feedback |
| **Export success rate** | ≥99% (no render failures) | Telemetry |

---

## 2. Problem Definition

### Current State (Manual)
```
Charge Nurse:
  1. Opens EHR → prints: MAR, Orders, Labs, Notes, Flowsheets
  2. Hand-writes: Handoff summary (SBAR), code status, isolation, mobility
  3. Cross-references: Allergies vs MAR, High-risk meds vs orders
  4. Assembles PDF: Prints → scans → orders pages per receiving unit spec
  5. Calls receiving unit → faxes/emails → confirms receipt
```
**Failure Modes**: Missed allergy, duplicate med, wrong code status, missing pending labs, page order wrong → receiving unit rejects or delays care.

### Desired State (SuperDocs Build)
```
Charge Nurse in SuperDocs:
  1. Uploads source docs (MAR, Orders, Labs, Notes, Flowsheets) — drag/drop
  2. System extracts → pre-fills structured handoff template
  3. Nurse reviews: Confirms ✓ / Edits ✎ each field (citations show source)
  4. High-risk fields (allergies, code status, high-risk meds) → MANDATORY confirm
  5. Med reconciliation: Auto-flags duplicates/dose mismatches → nurse resolves
  6. Export: One click → PDF packet (fixed order) + structured handoff doc
```

---

## 3. Scope & Requirements

### 3.1 Core Deliverables (Two Outputs)
| Output | Format | Purpose |
|--------|--------|---------|
| **Transfer Packet** | PDF (fixed page order) | Receiving unit consumption — print/fax ready |
| **Structured Handoff** | SuperDocs document (editable) | Source of truth; versioned; editable post-transfer |

### 3.2 Packet Page Order (Fixed, Non-Negotiable)
Per receiving unit standards (I-PASS / SBAR aligned):
```
1. Cover Sheet: Patient ID, Transfer Date/Time, Sending/Receiving Unit, Nurse Names
2. SBAR Handoff Summary: Situation, Background, Assessment, Recommendation
3. Allergies & Adverse Reactions (HIGH-RISK GATE)
4. Code Status (HIGH-RISK GATE)
5. Current Medication List (MAR) with Reconciliation Flags
6. High-Risk Medications (HIGH-RISK GATE) — anticoagulants, insulin, chemo, opioids, pressors
7. Active Orders (last 24h)
8. Pending Results (labs, imaging, cultures)
9. Isolation Status (Contact/Droplet/Airborne/None)
10. Mobility & Fall Risk Status
11. Source Documents Appendix (in fixed order: MAR → Orders → Labs → Notes → Flowsheets)
```

### 3.3 Functional Requirements

#### FR1: Multi-Document Ingestion
- Accept: PDF (scanned MAR, orders), DOCX (notes), CSV/Excel (labs), TXT (flows)
- Auto-classify by content + filename heuristics
- Extract structured data per doc type (see Extraction Specs below)

#### FR2: Structured Handoff Template (Pre-filled, Editable)
| Section | Source | Extraction Method |
|---------|--------|-------------------|
| Patient Demographics | MAR / Orders | Regex + NER |
| SBAR Summary | Notes (last 3) | LLM summarization with citations |
| Allergies | MAR / Orders / Notes | Consolidated list + source refs |
| Code Status | Notes / Orders | Explicit mention search |
| Med List | MAR | Structured parse (drug, dose, route, freq, start/stop) |
| High-Risk Meds | Med List + reference list | Rule-based flag (anticoagulant, insulin, etc.) |
| Active Orders | Orders (last 24h) | Parse + filter |
| Pending Results | Labs / Imaging | Status ≠ "final" or "resulted" |
| Isolation | Notes / Orders | Keyword + NER |
| Mobility/Fall Risk | Flowsheets / Notes | Scale scores (Morse, Braden) |

#### FR3: Medication Reconciliation (Conservative Flagging)
- **Duplicate detection**: Same generic + route + overlapping dates → FLAG (don't auto-resolve)
- **Dose mismatch**: Same drug, different dose across sources → FLAG
- **Omission risk**: Drug in Orders but not MAR (or vice versa) → FLAG
- **Interaction check**: High-risk combos (e.g., warfarin + antibiotic) → FLAG
- **Output**: Flags appear inline in Med List section with ⚠️; nurse must acknowledge each

#### FR4: High-Risk Field Gates (Export Blockers)
| Field | Gate Type | Behavior |
|-------|-----------|----------|
| Allergies | **Hard gate** | Export disabled until nurse clicks "Confirmed: Reviewed all sources" |
| Code Status | **Hard gate** | Export disabled until explicit selection (Full/Do Not Resuscitate/Partial) |
| High-Risk Meds | **Hard gate** | Each flagged med requires "Verified: Dose/Indication confirmed" |
| *All other fields* | Soft gate | Warning banner if unconfirmed; export allowed |

#### FR5: Review Interface (SuperDocs Review Mode)
- Side-by-side: Extracted field ↔ Source snippet (highlighted)
- Inline edit: Nurse changes value → citation updates
- Batch confirm: "Confirm all non-high-risk" button
- Audit trail: Every confirm/edit logged with timestamp + user

#### FR6: Export
- **PDF Packet**: Fixed page order, page numbers, receiving unit header/footer
- **Structured Handoff**: SuperDocs document (all fields editable, versioned)
- **Export Log**: JSON with all confirmations, flags, timestamps

---

## 4. Extraction Specifications (Per Document Type)

### 4.1 MAR (Medication Administration Record)
- **Format**: PDF (often scanned), sometimes CSV export
- **Fields**: `drug_name`, `generic_name`, `dose`, `unit`, `route`, `frequency`, `start_date`, `stop_date`, `status` (active/held/dc'd), `last_admin_time`
- **Method**: Table extraction (pdfplumber) → LLM normalization → generic mapping (RxNorm)

### 4.2 Orders (Provider Orders)
- **Format**: PDF, DOCX
- **Fields**: `order_type` (med/lab/imaging/consult/diet/activity), `details`, `ordering_provider`, `date_time`, `status` (active/completed/cancelled)
- **Method**: Section detection → structured parse

### 4.3 Labs & Imaging
- **Format**: PDF, CSV, HL7 (if available)
- **Fields**: `test_name`, `result`, `unit`, `ref_range`, `status`, `collection_time`, `result_time`, `abnormal_flag`
- **Pending** = status ∈ {pending, in_process, collected, verified_not_resulted}

### 4.4 Clinical Notes (Progress, Transfer, Discharge)
- **Format**: DOCX, PDF, TXT
- **Fields**: `note_type`, `author`, `date_time`, `full_text`, `extracted_entities` (allergies, code_status, isolation, mobility_scores, diagnoses)
- **Method**: LLM with schema-constrained output (Pydantic)

### 4.5 Flowsheets (Vitals, I&O, Assessments)
- **Format**: CSV, PDF
- **Fields**: `assessment_type` (Morse Fall, Braden, Pain, Neuro), `score`, `risk_level`, `date_time`
- **Method**: Column mapping → latest per assessment type

---

## 5. Technical Architecture (SuperDocs Build)

### 5.1 Integration Pattern
**MCP-first** (per task guidance): Build as MCP tools callable from SuperDocs chat + standalone script for batch.

| MCP Tool | Purpose |
|----------|---------|
| `upload_clinical_docs` | Accept multiple files → return doc_ids |
| `build_handoff_packet` | Trigger extraction + template population |
| `review_handoff` | Present fields for confirmation (Review mode) |
| `confirm_field` | Record nurse confirmation (field_id, value, confirmed) |
| `export_packet` | Generate PDF + structured doc (blocks if gates open) |

### 5.2 Data Flow
```
Upload → SuperDocs Document Store
    ↓
Extraction Pipeline (per doc type) → Structured JSON
    ↓
Template Engine (Jinja2 for PDF, SuperDocs doc for handoff)
    ↓
Review Mode UI (SuperDocs native) → Nurse confirms/edits
    ↓
Export → PDF (fixed order) + SuperDocs Document
```

### 5.3 SuperDocs Features Leveraged
- **Upload API**: Multi-file, progress tracking
- **Chat/Edit**: Instruction → proposed changes → review cards
- **Review Mode**: Citation survival, granular approve/reject
- **Export API**: PDF + native format
- **Templates**: Reusable handoff template with placeholders

---

## 6. Non-Functional Requirements

| Requirement | Spec |
|-------------|------|
| **PHI Handling** | No PHI in logs; temp files encrypted at rest; purge after export |
| **Latency** | Extraction < 60s/doc; Review UI < 2s interaction; Export < 10s |
| **Availability** | Runs on SuperDocs cloud; no self-hosted infra needed |
| **Audit** | Every confirm/edit/export logged with user + timestamp |
| **Offline** | Not required (hospital WiFi assumed) |

---

## 7. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| MAR format variance (vendor-specific) | High | High | Configurable table extraction rules per hospital; fallback to LLM |
| Scanned PDF OCR errors | Medium | High | Confidence scoring; low-confidence → flag for manual entry |
| Nurse workflow interruption | Medium | Medium | Auto-save every 30s; resume from last confirmed field |
| Receiving unit format changes | Low | Medium | Template versioning; config-driven page order |
| SuperDocs API rate limits | Low | Medium | Batch operations; respect retry-after |

---

## 8. Milestones & Definition of Done

| Milestone | Deliverable | DoD |
|-----------|-------------|-----|
| **M1: Ingestion & Classification** | Upload 5 doc types → correct classification | 20/20 synthetic docs classified correctly |
| **M2: Extraction Pipeline** | Each doc type → structured JSON with citations | All fields populated; source_refs valid |
| **M3: Template Population** | JSON → SuperDocs handoff template (pre-filled) | Template renders with zero empty required fields |
| **M4: Med Reconciliation** | Duplicate/dose/omission flags on test set | 100% known duplicates flagged; 0 false negatives |
| **M5: High-Risk Gates** | Export blocked until all 3 gates confirmed | Automated test: export fails with open gate; passes when all closed |
| **M6: Review UI** | SuperDocs review mode with side-by-side citations | Nurse can confirm/edit each field; citations persist |
| **M7: PDF Export** | Fixed-order PDF + structured handoff doc | PDF matches page order spec; handoff doc editable |
| **M8: End-to-End Pilot** | 3 complete transfers with synthetic data | Time ≤15 min; zero missing sections; all gates work |
| **M9: PR to superdocs-builds** | Code + README + demo video | Merged; passes CI; demo shows real workflow |

---

## 9. Synthetic Test Data Strategy

Create 3 patient scenarios (no PHI):
1. **Standard ICU Transfer**: 5 docs, 12 meds, 2 flags, 1 pending lab
2. **Complex Polypharmacy**: 18 meds, 4 duplicates, warfarin+antibiotic interaction, code status change
3. **Edge Case**: Scanned MAR (poor OCR), handwritten note photo, missing orders doc

All test data in `test_data/nursing_handoff/` (committed).

---

## 10. Open Decisions

| Decision | Options | Recommendation |
|----------|---------|----------------|
| Generic name mapping | RxNorm API (requires UMLS license) vs local CSV | **Local CSV** (RxNorm subset) for demo; API for prod |
| High-risk med list | Hardcoded vs configurable YAML | **Configurable YAML** (hospital-specific) |
| PDF generation | WeasyPrint vs reportlab vs SuperDocs export | **SuperDocs export** (native, citation survival) |
| Receiving unit variants | Single fixed order vs config per unit | **Config per unit** (JSON); default = I-PASS standard |

---

## 11. Appendix: Receiving Unit Packet Spec (Example)

```
RECEIVING UNIT: [Unit Name] TRANSFER PACKET v2.1
==================================================
PAGE 1: COVER SHEET
  Patient: [Last, First]  MRN: [####]  DOB: [MM/DD/YYYY]
  Transfer: [Date] [Time]  From: [Unit]  To: [Unit]
  Sending RN: [Name]  Receiving RN: [Name]

PAGE 2: SBAR HANDOFF
  SITUATION: [1-2 sentences]
  BACKGROUND: [Key history, admission reason]
  ASSESSMENT: [Current clinical picture]
  RECOMMENDATION: [Anticipated needs, warnings]

PAGE 3: ALLERGIES █ GATE REQUIRED
  □ NKDA  □ Latex  □ [Drug: Reaction]  Source: [MAR p.2 / Note p.1]
  CONFIRMED BY: _______________  TIME: _______

PAGE 4: CODE STATUS █ GATE REQUIRED
  □ Full Code  □ DNR  □ DNI  □ Partial: __________
  Source: [Note p.3 / Order p.1]
  CONFIRMED BY: _______________  TIME: _______

PAGE 5: MEDICATION LIST (with flags ⚠️)
  Drug | Dose | Route | Freq | Last Given | Status | Flag
  ─────────────────────────────────────────────────────
  Heparin | 5000U | SubQ | q8h | 06:00 | Active | ⚠️ Duplicate?
  Metoprolol | 25mg | PO | BID | 08:00 | Active |

PAGE 6: HIGH-RISK MEDS █ GATE REQUIRED
  Drug | Verification Required
  ─────────────────────────────
  Heparin | Dose/Indication confirmed □
  Insulin | Dose/Indication confirmed □

PAGE 7: ACTIVE ORDERS (Last 24h)
  [Table: Type | Details | Provider | Time | Status]

PAGE 8: PENDING RESULTS
  [Table: Test | Ordered | Status | Expected]

PAGE 9: ISOLATION
  □ None  □ Contact  □ Droplet  □ Airborne  □ Enhanced
  Precautions: ________________

PAGE 10: MOBILITY / FALL RISK
  Morse Fall Score: __/125  Level: [Low/Mod/High]
  Braden Score: __/23  Risk: [Mild/Mod/High/None]
  Mobility: [Independent/Assist/Dependent]

PAGES 11+: SOURCE DOCUMENTS (in order)
  1. MAR (all pages)
  2. Provider Orders (last 24h)
  3. Lab Results (pending + last 24h final)
  4. Clinical Notes (last 3 progress + transfer note)
  5. Flowsheets (last 24h vitals, assessments)
```