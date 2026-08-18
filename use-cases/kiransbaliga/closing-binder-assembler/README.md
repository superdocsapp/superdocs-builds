# M&A Closing-Binder Assembler
**Automated Semantic Matching, Signature Execution Auditing & Navigable PDF Binder Engine**

> **SuperDocs Engineering Round 2 — Task 2 (Assigned Build)**  
> **Difficulty Band**: S3  
> **Author**: Kiran Baliga (`kiransbaliga`)  
> **Credit Line**: *Built for the SuperDocs engineering task.*

---

## 1. Executive Summary & Problem Space

In corporate M&A transactions ($50M to $10B+ deals), closing involves between **60 and 200+ distinct legal instruments**:
- Primary Transaction Agreements (Merger Agreement, Escrow Agreement, Paying Agent Agreement)
- Ancillary & Commercial Contracts (Transition Services, IP Assignment, Restrictive Covenants)
- Corporate Governance & Approvals (Certificates of Incorporation, Delaware Articles of Merger, Board & Stockholder Written Consents, Good Standing Certificates)
- Regulatory & Third-Party Consents (FTC/DOJ HSR clearance, Landlord Consents)
- Officer Certificates & Legal Opinions (Incumbency, Closing Bring-Down, Solvency, 368 Tax Opinion)
- Financial & Funds Flow Deliverables (Funds Flow Memo, Debt Payoff Letters, UCC-3 Terminations)
- Disclosure Schedules & Capitalization Tables

### The Closing Friction
When files are collected at 3 AM on closing night:
1. **Chaotic Naming**: Incoming files have arbitrary, non-standardized names (`scan_00192.pdf`, `agmt_clean_v2.docx`, `Project_Titan_Merger_Agmt_Execution_FINAL_v4_signed.pdf`).
2. **Execution Gaps**: Documents often arrive unexecuted (`By: _________`), partially signed (missing buyer or seller countersignature), or as draft redlines.
3. **Manual Assembly Burden**: Paralegals and junior associates spend 20–40 tedious hours manually matching files to the 100-line Closing Checklist, detecting missing signatures, building manual indexes, creating tab dividers, stamping running headers, merging PDFs, and typing outstanding deficiency emails.

### The Solution: M&A Closing-Binder Assembler
An intelligent, production-ready legaltech engine that:
1. **Semantically Matches** multi-format files (PDF, DOCX, TXT) to checklist lines based on legal titles, recitals, defined terms, and party entity signatures—surviving completely arbitrary filenames.
2. **Accurately Audits Signature Execution** (distinguishes DocuSign envelopes, Adobe Sign audit trails, wet ink signatures, and non-signature state certificates from unexecuted blank draft lines `By: _________`).
3. **Assembles a Single Navigable PDF Binder** with an executive cover page, a **live hyperlinked Table of Contents (PDF Link Annotations that jump straight to target pages)**, elegant Tab Dividers, running headers (`Project Titan | Tab 01: ...`), running page numbers (`Page X of Y`), and a native PDF Outline/Bookmarks tree.
4. **Organizes a Clean Per-Document Folder & ZIP Package** categorized by deal sections.
5. **Generates a Client-Ready Outstanding Items Report** (PDF & Markdown) with closing readiness score, blocker tables, and next actions that transactional partners can email to clients unedited.
6. **Integrates with SuperDocs REST & MCP Surface** using the 4-call contract (`upload`, `chat`, `approve`, `export`) with JSON string double-parse safety and budget controls.

---

## 2. Architectural Overview

```
+----------------------------------------------------------------------------------------------------+
|                                           CLIENT SURFACES                                          |
|  +-----------------------------------------------------+  +-------------------------------------+  |
|  |             Interactive Deal Review Dashboard       |  |      Model Context Protocol (MCP)   |  |
|  |  * Drag-and-drop bundle upload * Match review table |  |  * Claude/Cursor/Agent integration  |  |
|  |  * Live execution badges       * 1-Click assembly   |  |  * Programmatic 4-tool interface    |  |
|  +-----------------------------------------------------+  +-------------------------------------+  |
+----------------------------------------------------------------------------------------------------+
                                                  | REST / JSON-RPC
+----------------------------------------------------------------------------------------------------+
|                               FASTAPI ENGINE & BUSINESS LOGIC PIPELINE                             |
|                                                                                                    |
|   +--------------------------------------------------------------------------------------------+   |
|   | 1. CHECKLIST & MULTI-FORMAT INGESTION ENGINE (PDF, DOCX, TXT, MD, Scanned OCR)            |   |
|   +--------------------------------------------------------------------------------------------+   |
|                                                  |                                                 |
|   +--------------------------------------------------------------------------------------------+   |
|   | 2. SIGNATURE & EXECUTION AUDITOR (DocuSign, AdobeSign, Wet Ink, Blank Line Heuristic)     |   |
|   +--------------------------------------------------------------------------------------------+   |
|                                                  |                                                 |
|   +--------------------------------------------------------------------------------------------+   |
|   | 3. MULTI-SIGNAL SEMANTIC MATCHER (Title similarity, Entity alignment, TF-IDF n-grams)      |   |
|   +--------------------------------------------------------------------------------------------+   |
|                                                  |                                                 |
|   +--------------------------------------------------------------------------------------------+   |
|   | 4. NAVIGABLE PDF BINDER ENGINE (ReportLab + PyPDF Link Annotations, Dividers, Headers)     |   |
|   +--------------------------------------------------------------------------------------------+   |
|                                                  |                                                 |
|   +--------------------------------------------------------------------------------------------+   |
|   | 5. EXPORTER (Categorized Per-Doc Folder, ZIP, Client-Ready Outstanding Items PDF & MD)     |   |
|   +--------------------------------------------------------------------------------------------+   |
+----------------------------------------------------------------------------------------------------+
                                                  |
+----------------------------------------------------------------------------------------------------+
|                                SUPERDOCS API & MCP CONNECTOR LAYER                                 |
|  * Call 1: upload_document()          * Call 2: chat_edit_instruction() [Double-Parse Safe]       |
|  * Call 3: approve_changes()          * Call 4: export_deliverable() [Zero Operation Cost]        |
|  * Offline Mock Adapter: 100% test coverage without live keys                                      |
+----------------------------------------------------------------------------------------------------+
```

---

## 3. The 3 Primary Deliverables

| Deliverable | Format | Description |
| :--- | :--- | :--- |
| **1. Master Navigable PDF Binder** | `.pdf` | Single unified document with executive cover page, **clickable Table of Contents with internal PDF Link Annotations**, full-page tab dividers, running headers, running page counts, and native PDF bookmarks. |
| **2. Per-Document Folder & ZIP** | Directory / `.zip` | Normalized, clean file structure organized into numbered subdirectories (e.g. `01_Primary_Transaction_Agreements/Tab_01_Agreement_and_Plan_of_Merger.pdf`) with JSON manifest and Markdown index. |
| **3. Client-Ready Outstanding Items Report** | `.pdf` & `.md` | Polished executive memorandum featuring closing readiness percentage, critical closing blockers table, incomplete signature deficiencies table, and satisfied items index. |

---

## 4. SuperDocs API & MCP Surface Integration

This build connects natively to the SuperDocs platform via REST and Model Context Protocol (MCP):

### The 4 Core Calls:
1. `upload_document`: Ingests closing checklist or incoming transaction documents.
2. `chat_edit_instruction`: Sends targeted prompts to analyze or reformat document clauses. **Includes built-in double-parse handling for SuperDocs' JSON-encoded string responses.**
3. `approve_changes`: Approves diff cards to commit changes.
4. `export_deliverable`: Exports clean deliverables without consuming operations.

### Exposed MCP Tools:
- `assemble_closing_binder`: Executes end-to-end assembly.
- `match_documents_to_checklist`: Semantic matching over document pools.
- `detect_unsigned_documents`: Audits execution and signature blocks.
- `generate_outstanding_items_report`: Generates client-ready deficiency memorandum.

---

## 5. Quick Start & Usage

### 1. Run Offline Tests (100% Pass in < 1 Second)
No API key required:
```bash
pytest use-cases/kiransbaliga/closing-binder-assembler/tests -v
```

### 2. Run via Command Line (CLI)
```bash
python -m use-cases.kiransbaliga.closing-binder-assembler.cli.main \
  --checklist use-cases/kiransbaliga/closing-binder-assembler/samples/project_titan_checklist.json \
  --documents-dir use-cases/kiransbaliga/closing-binder-assembler/samples/executed_documents \
  --output-dir ./output_binder
```

### 3. Run the Web Review Dashboard & API
```bash
uvicorn use-cases.kiransbaliga.closing-binder-assembler.api.server:app --reload --port 8000
```
Then open `http://localhost:8000` in your browser. Click **"⚡ Load Sample Project Titan Deal"** and **"🚀 Assemble Closing Binder"** to view and download all deliverables with 1 click.

---

## 6. Verification & Test Proof

| Test Suite | Coverage & Behaviors Proven |
| :--- | :--- |
| `test_checklist_parser.py` | Validates parsing 65+ checklist items across JSON, Markdown tables, and CSV. |
| `test_signature_detector.py` | Proves detection of DocuSign, wet signatures, typed signatures, blank lines (`By: _____`), and state certificates with 0 false positives. |
| `test_semantic_matcher.py` | Proves semantic matching survives obscure/messy filenames (`scan_00192.pdf` $\to$ Good Standing, `agmt_clean_v2.docx` $\to$ Escrow). |
| `test_pdf_binder_assembler.py` | Proves generation of PDF cover page, hyperlinked TOC, tab dividers, bookmarks tree, and running headers. |
| `test_outstanding_report.py` | Validates client-ready PDF and Markdown deficiency report generation with readiness score calculation. |
| `test_superdocs_integration.py` | Validates 4-call API contract, JSON double-parse safety, and MCP server tool dispatching. |
| `test_end_to_end.py` | Validates full pipeline from raw files to all 3 finished deliverables. |

---

## 7. License & Credits

- **License**: MIT License
- **Credit Line**: Built by **Kiran Baliga** for the **SuperDocs Engineering Task (Round 2)**.
