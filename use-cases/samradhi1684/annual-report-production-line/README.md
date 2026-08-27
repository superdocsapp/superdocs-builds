# Annual Report Production Line

A production workflow for building, reviewing, validating, and exporting a multi-document annual report using the **SuperDocs REST API**.

Built for the SuperDocs Engineer Task — **Assigned Build: Annual and integrated report production line**.

The workflow treats an annual report as a linked document set rather than a collection of unrelated files. It tracks review stages across sections, checks house style, validates repeated figures across documents, and uses SuperDocs export to produce the final PDF and HTML deliverables.

---

## Quick Start

```bash
# 1. Clone and enter the project
git clone <your-repo-url>
cd annual-report-production-line

# 2. Install dependencies (creates .venv and installs requirements.txt)
bash setup.sh           # Linux / macOS
# .\setup.ps1           # Windows PowerShell

# 3. Activate the virtual environment (after first run)
source .venv/bin/activate          # Linux / macOS
# .\.venv\Scripts\Activate.ps1     # Windows PowerShell

# 4. Set your SuperDocs API key
export SUPERDOCS_API_KEY="your-api-key"    # Linux / macOS
# $env:SUPERDOCS_API_KEY="your-api-key"   # Windows PowerShell

# 5. Run the MCP server (exposes the full pipeline as MCP tools)
python3 mcp_server.py
```

Or run the pipeline steps individually without the MCP server:

```bash
python3 test_multidoc.py       # upload all five report sections
python3 consistency_check.py  # check figures across documents
python3 house_style.py        # validate house style rules
python3 export.py             # export final PDF + HTML
```

---

## Overview

Annual reports are assembled from multiple contributors and typically pass through several review rounds before publication.

This build models that workflow around five linked report sections:

1. Chair Statement
2. Strategy
3. Business Review
4. Governance
5. Financial Statements

The production pipeline provides:

- Multi-document report management
- Review-stage persistence
- House-style enforcement
- Cross-document number consistency checking
- SuperDocs-powered export
- PDF output
- Plain HTML output
- Reproducible validation
- A finalization gate

---

# Assigned Build

## Annual and integrated report production line

### Intended user

Publishing, corporate communications, or reporting managers working on annual or integrated reports at listed or large private companies.

### Core workflow

```text
Narrative
├── Chair Statement
├── Strategy
├── Business Review
└── Governance

Financial
└── Financial Statements
```

Each section is independently tracked while remaining part of the same report session.

---

# SuperDocs integration

This project is built **on SuperDocs**, rather than attempting to recreate SuperDocs locally.

The integration uses the SuperDocs REST API.

Base API:

```text
https://api.superdocs.app
```

Authentication:

```text
SUPERDOCS_API_KEY
```

## Document upload

```http
POST /v1/documents/upload
```

Each report section is uploaded to a shared SuperDocs session.

## Export

```http
POST /v1/documents/export
```

The current session is exported through SuperDocs to:

- PDF
- HTML

The final PDF is **not** produced by a local HTML-to-PDF converter. The export is performed through the SuperDocs export surface.

---

# Report state

The report maintains a persistent state file:

```text
report_state.json
```

Example:

```json
{
  "report_title": "Annual Report 2026",
  "session_id": "annual-report-multidoc-test",
  "documents": {
    "Chair Statement": {
      "filename": "chair-statement.html",
      "document_id": "doc_primary",
      "stage": "draft"
    },
    "Strategy": {
      "filename": "strategy.html",
      "document_id": "doc_0bf9096a34",
      "stage": "editorial_review"
    },
    "Business Review": {
      "filename": "business-review.html",
      "document_id": "doc_8547437129",
      "stage": "finance_review"
    },
    "Governance": {
      "filename": "governance.html",
      "document_id": "doc_a67db7f637",
      "stage": "legal_review"
    },
    "Financial Statements": {
      "filename": "financial-statements.html",
      "document_id": "doc_2b79b3b153",
      "stage": "approved"
    }
  }
}
```

Review state is persisted rather than kept only in process memory, so the workflow can be inspected and resumed after reloads.

---

# Review stages

The workflow models:

```text
draft
   ↓
editorial_review
   ↓
finance_review
   ↓
legal_review
   ↓
approved
```

Example state:

| Section | Review stage |
|---|---|
| Chair Statement | draft |
| Strategy | editorial_review |
| Business Review | finance_review |
| Governance | legal_review |
| Financial Statements | approved |

This represents an annual-report production cycle where different sections can be at different review stages simultaneously.

---

# Number consistency checking

A core requirement is ensuring that figures appearing in multiple places remain consistent.

The sample report contains repeated figures such as:

```text
£120 million
4,500 people
32%
```

The consistency checker compares repeated figures across the report documents.

Example:

```text
Revenue
────────────────────────────────────────
Chair Statement       £120 million
Business Review       £120 million
Financial Statements  £120 million

Status: MATCH
```

Example mismatch:

```text
Business Review:
Revenue was £120 million.

Financial Statements:
Revenue was £125 million.

Status: MISMATCH
```

The consistency report records:

- total findings
- matches
- mismatches
- affected documents
- individual values

Output:

```text
number-consistency-report.json
```

This creates an explicit quality gate before publication.

---

# House style enforcement

Implemented in:

```text
house_style.py
```

The validator checks every report document against common house-style rules.

## Character encoding

Detects common mojibake such as:

```text
Â£
â€“
â€™
â€œ
```

For example:

```text
Â£120 million
```

is rejected in favor of:

```text
£120 million
```

## Currency formatting

Preferred:

```text
£120 million
```

Flagged alternatives include:

```text
£120m
GBP 120 million
GBP120m
£120b
```

## Percentage formatting

Preferred:

```text
32%
```

rather than:

```text
32 percent
```

## Employee count formatting

Preferred:

```text
4,500 people
```

rather than:

```text
4500 people
```

## Heading structure

Every document must contain:

- exactly one `<h1>`
- at least one `<h2>`
- an `<h1>` matching the expected document title

Example:

```html
<h1>Strategy</h1>
```

## HTML document title

The HTML `<title>` must match the report section:

```html
<title>Strategy</title>
```

## Report year

Documents must contain an expected reporting year.

---

# House-style finalization gate

If all documents pass:

```text
HOUSE STYLE STATUS: PASS
All 5 documents passed the house style checks.
```

If violations exist:

```text
HOUSE STYLE STATUS: REVIEW REQUIRED
```

The script exits with a non-zero status on failure, making it suitable as a pipeline/CI gate.

---

# Export pipeline

The final report is exported directly through the SuperDocs export endpoint.

Implementation:

```text
export.py
```

PDF request:

```json
{
  "session_id": "annual-report-multidoc-test",
  "format": "pdf",
  "options": {
    "filename": "annual-report-2026"
  }
}
```

HTML request:

```json
{
  "session_id": "annual-report-multidoc-test",
  "format": "html",
  "options": {
    "filename": "annual-report-2026"
  }
}
```

Outputs:

```text
output/
├── annual-report-2026.pdf
└── annual-report-2026.html
```

The exported HTML contains:

```text
Chair Statement
Strategy
Business Review
Governance
Financial Statements
```

---

# Production workflow

## 1. Prepare source documents

```text
documents/
├── chair-statement.html
├── strategy.html
├── business-review.html
├── governance.html
└── financial-statements.html
```

## 2. Upload the report set to SuperDocs

```powershell
python test_multidoc.py
```

This uploads the five documents to the shared SuperDocs session and records their document IDs in:

```text
report_state.json
```

## 3. Run number consistency checking

```powershell
python consistency_check.py
```

Output:

```text
number-consistency-report.json
```

Unresolved mismatches should block publication.

## 4. Run house-style validation

```powershell
python house_style.py
```

Expected successful result:

```text
HOUSE STYLE STATUS: PASS
All 5 documents passed the house style checks.
```

## 5. Export the final report through SuperDocs

```powershell
python export.py
```

This calls:

```text
POST /v1/documents/export
```

for both PDF and HTML.

---

# Complete workflow

```text
                SOURCE DOCUMENTS
                       │
                       ▼
              SuperDocs Upload
                       │
                       ▼
             Shared Report Session
                       │
          ┌────────────┼────────────┐
          │            │            │
          ▼            ▼            ▼
     Review State   Consistency  House Style
          │          Checking       Check
          │            │            │
          └────────────┼────────────┘
                       │
                       ▼
                FINALIZATION GATE
                       │
                       ▼
               SuperDocs Export
                  /                           ▼            ▼
               PDF          HTML
```

---

# Project structure

```text
annual-report-production-line/
│
├── documents/
│   ├── chair-statement.html
│   ├── strategy.html
│   ├── business-review.html
│   ├── governance.html
│   └── financial-statements.html
│
├── output/
│   ├── annual-report-2026.pdf
│   └── annual-report-2026.html
│
├── test_multidoc.py
├── consistency_check.py
├── house_style.py
├── export.py
│
├── report_state.json
├── number-consistency-report.json
│
└── README.md
```

---

# Running the project

## Requirements

Python 3.9+. Install all dependencies with:

```bash
pip install -r requirements.txt
```

Set the SuperDocs API key before running any script:

```bash
export SUPERDOCS_API_KEY="your-api-key"   # Linux / macOS
$env:SUPERDOCS_API_KEY="your-api-key"     # PowerShell
```

Never commit the API key.

---

# Run the workflow

### Upload

```bash
python test_multidoc.py
```

### Consistency validation

```bash
python consistency_check.py
```

### House-style validation

```bash
python house_style.py
```

### Export

```bash
python export.py
```

---

# Design principles

## 1. SuperDocs is the document engine

This project does not attempt to replace SuperDocs with a local document renderer.

SuperDocs handles document operations and final export.

The local code provides the domain-specific production-line orchestration and validation around the SuperDocs API.

## 2. The annual report is one linked report

The report consists of multiple source documents, but they belong to one reporting session.

The workflow therefore reasons about:

```text
documents
review stages
shared figures
style rules
final output
```

as one publication process.

## 3. Validation happens before publication

The workflow separates:

```text
editing
    ↓
review
    ↓
validation
    ↓
publication
```

A report is not considered final simply because all documents exist.

It should also pass:

- number consistency checks
- house-style validation
- final export

## 4. State is explicit

Review state is stored in a durable JSON representation rather than inferred from filenames or temporary program state.

## 5. Small, composable scripts

```text
test_multidoc.py
    Upload and register report documents

consistency_check.py
    Check repeated figures across documents

house_style.py
    Validate common report style

export.py
    Produce final PDF and HTML through SuperDocs
```

---

# Mapping to the assigned task

| Task requirement | Implementation |
|---|---|
| Multi-document report | Five report sections uploaded into one SuperDocs session |
| Linked document set | Shared session + persisted document IDs |
| Review-round state | `report_state.json` |
| State survives reloads | State persisted to disk |
| House style | `house_style.py` |
| Consistent figures | `consistency_check.py` |
| Number-consistency report | `number-consistency-report.json` |
| Final PDF | SuperDocs `/v1/documents/export` |
| Plain HTML | SuperDocs `/v1/documents/export` |
| REST API integration | SuperDocs REST endpoints |
| Production workflow | Upload → review → validate → export |
| Final repository location | `use-cases/` |

---

# Why this is more than a document merger

The goal is not simply:

```text
5 HTML files → 1 HTML file
```

The production line adds controls around the report lifecycle:

```text
                DOCUMENT SET
                     │
                     ▼
             REVIEW MANAGEMENT
                     │
                     ▼
          CROSS-DOCUMENT VALIDATION
                     │
             ┌───────┴───────┐
             ▼               ▼
        NUMBER CHECK     HOUSE STYLE
             │               │
             └───────┬───────┘
                     ▼
               FINAL EXPORT
                     │
             ┌───────┴───────┐
             ▼               ▼
            PDF             HTML
```

This models a reporting-team workflow rather than merely demonstrating file conversion.

---

# Example report data

The sample report deliberately contains recurring figures:

```text
Revenue
£120 million

Employees
4,500 people

Operational carbon emissions
32%
```

These provide realistic cross-document validation cases.

To demonstrate mismatch detection, change one occurrence, for example:

```text
Business Review:
£120 million
```

to:

```text
Business Review:
£125 million
```

The consistency check should then identify the discrepancy.

---

# Current status

Implemented:

- [x] Five-document annual report
- [x] Shared SuperDocs session
- [x] SuperDocs document upload
- [x] Persistent report state
- [x] Independent review-stage tracking
- [x] Cross-document number consistency checking
- [x] Number-consistency report
- [x] House-style enforcement
- [x] Encoding validation
- [x] Currency validation
- [x] Percentage validation
- [x] Employee-count validation
- [x] Heading validation
- [x] Document-title validation
- [x] Report-year validation
- [x] SuperDocs PDF export
- [x] SuperDocs HTML export
- [x] Final output artifacts

Potential extensions:

- [ ] Connect review-stage transitions directly to SuperDocs Review/approval operations
- [ ] Add automated style-fix proposals through SuperDocs
- [ ] Add publication blocking based on unresolved consistency findings
- [ ] Add richer annual-report templates
- [ ] Add images and reusable report assets
- [ ] Add production-quality pagination/running-head configuration
- [ ] Add CI validation for the full pipeline

---

# Relationship to SuperDocs

This project is intentionally an application built **on top of SuperDocs**.

SuperDocs provides the document-processing and export layer.

This project adds the domain-specific annual-report production workflow around it:

```text
SuperDocs
   │
   ├── Document upload
   ├── Document/session state
   ├── Document operations
   └── Final export
            │
            ▼
Annual Report Production Line
   │
   ├── Report structure
   ├── Review state
   ├── Number consistency
   ├── House style
   └── Publication workflow
```

The result is a domain-specific corporate-reporting workflow rather than a reimplementation of SuperDocs.

---

# Task 2 alignment

This implementation targets the assigned:

> **Annual and integrated report production line**

for:

> **Publishing / corporate communications or reporting managers**

The build focuses on:

```text
multi-document report
        +
review stages
        +
house style
        +
cross-document figures
        +
PDF export
        +
HTML export
```

The final implementation is intended to be submitted under:

```text
use-cases/
```

as a pull request to the public repository.

---

# Security

The SuperDocs API key is never stored in the repository.

Set it using:

```text
SUPERDOCS_API_KEY
```

Do not commit:

```text
.env
API keys
access tokens
credentials
```

---

# Author

Built as part of the **SuperDocs Engineer Task — Task 2**.

**Assigned build:** Annual and integrated report production line

**Integration:** SuperDocs REST API

**Primary focus:** Multi-document annual-report production, validation, and publication.
