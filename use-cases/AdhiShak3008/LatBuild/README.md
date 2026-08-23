# LatBuild — SuperDocs PDF Companion

A SuperDocs-powered surgical PDF editing tool that lets you rewrite any section of an existing PDF while preserving the original document's visual layout, columns, typography, figures, and page structure.

**Built for:** The SuperDocs Engineer Task — Round 2  
**Author:** AdhiShak3008

---

## The Problem

When you upload an 11-page IEEE two-column paper to standard AI editors and ask to rewrite a section (such as the Abstract or Introduction), the exported document often loses the two-column grid, reflows uncontrollably, and distorts the document geometry into an unformatted wall of prose.

**The semantic edit succeeds, but physical document fidelity fails.**

LatBuild solves this by keeping SuperDocs responsible for the high-quality prose transformation while LatBuild performs deterministic PDF surgery:

```
SuperDocs sees:   clean section prose
SuperDocs returns: edited section prose
LatBuild does:    layout analysis, flow region mapping, typography calibration, 
                  two-column reflow, immutable redaction, and fidelity verification
```

---

## How It Works

```
Upload PDF
  ↓
PDF Analyzer (pdfplumber + PyMuPDF)
  ↓ extracts: columns, gutters, margins, fonts, line height, headings, text blocks, preamble
DocumentFlowMap
  ↓ maps: sections → ordered text blocks → continuous flow regions
User selects sections & enters instructions (global or per-section)
  ↓
Section Extractor
  ↓ extracts clean prose per section + calculates layout word budget (±5%)
SuperDocs API (upload .docx → async transformation → structured changes)
  ↓ returns: proposed edits / transformed text
Diff Review & Approval
  ↓ user approves / rejects changes per section
Reflow Engine
  ↓ measures replacement typography, formats paragraphs, distributes across flow regions
PDF Patcher (PyMuPDF)
  ↓ redacts original regions, inserts replacement text with calibrated line height
  ↓ NEVER touches figures, tables, headers, or non-target pages (strict invariant)
Fidelity Checker
  ↓ pixel-level and structural validation (page count, figures preserved, non-target pages untouched)
Download modified PDF
```

---

## Key Capabilities & Engineering Highlights

### 1. Two-Column & Multi-Page Flow Management
- **True Gutter Detection**: Employs zero-count histogram binning across page centers to identify the exact column gutter (e.g. 12pt IEEE standard), preventing column squishing or text collision.
- **Top Header Banner Isolation**: Automatically isolates top title and author blocks spanning across Page 1 columns so they are never absorbed into body sections.
- **Continuous Cross-Column / Cross-Page Reflow**: Seamlessly distributes multi-paragraph rewrites across Column 0, Column 1, and subsequent pages (e.g. Introduction or Conclusion spanning Pages 1–2 or Pages 11–12).

### 2. Typography & Layout Calibration
- **LaTeX-Matched Baseline Pitch**: Calibrates line-height ratios (`1.12–1.15`) and paragraph breaks (`re.sub(r'\n{2,}', '\n', ...)`) to match authentic IEEE LaTeX typesetting, eliminating artificial overflow or trailing white gaps.
- **Inline Run-in Heading Support**: Special handling for inline headings (`Abstract —`, `Keywords —`) starting from line 0 without duplicate text artifacts.
- **Unicode Font Safety**: Automatically sanitizes unicode em-dashes and en-dashes (`\u2014` → `--`) for standard PDF fonts, preventing question mark (`?`) rendering artifacts.

### 3. Resilient Change Mapping & Review
- **Multi-Tier Span Matching**: Uses exact substring, token-normalized window comparison, and fuzzy `SequenceMatcher` fallback to cleanly map SuperDocs diffs back to the original manuscript without mapping errors.
- **Granular Decision Control**: Users can review original vs. proposed text per section, approving or rejecting changes individually before applying them to the PDF.

---

## Architecture

```
service/
├── pdf_analyzer.py       — pdfplumber & PyMuPDF: layout geometry, grammar, headings, text blocks
├── flow_mapper.py        — sections, FlowRegions, DocumentFlowMap
├── section_extractor.py  — clean prose extraction, word budget calculation (±5%)
├── docx_bridge.py        — prose ↔ .docx roundtrip (for SuperDocs API)
├── superdocs_client.py   — SuperDocs REST API integration (upload, async chat, poll, approve)
├── reflow_engine.py      — text measurement, region capacity, cross-column distribution
├── pdf_patcher.py        — PyMuPDF: atomic redaction + insertion, typography rendering
├── fidelity_checker.py   — pixel diff, structural validation, fidelity reporting
└── app.py                — Flask backend: routing, session state, review UI, and orchestration
```

**Core Data Structures:**
- `DocumentGrammar`: Visual specifications of the document (body font, size, line height, margins, column count, gutter width).
- `DocumentFlowMap`: Ordered map of document sections linked to physical `FlowRegion` bounding boxes.
- `FlowRegion`: Physical bounding box (`page`, `column`, `bbox`, `heading_bottom_y`) through which replacement prose flows.
- `ReflowResult`: Complete plan containing section patches, capacity verification, and overflow status.
- `FidelityReport`: Verification report proving non-target pages, figures, and total page counts remain 100% intact.

---

## Setup & Running

### Prerequisites
- Python 3.10+
- SuperDocs API key from [use.superdocs.app](https://use.superdocs.app)

### 1. Install Dependencies

```powershell
cd use-cases/AdhiShak3008/LatBuild/service
python -m venv .venv
.venv\Scripts\activate          # Windows PowerShell
# source .venv/bin/activate     # macOS/Linux
pip install -r requirements.txt
```

### 2. Configure Environment

Create a `.env` file in `use-cases/AdhiShak3008/LatBuild/service/` or `LatBuild/`:
```env
SUPERDOCS_API_KEY=your_actual_api_key_here
```

### 3. Start the Application

```powershell
# Windows PowerShell:
Get-ChildItem -Path . -Include __pycache__, .pytest_cache -Recurse -Force | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue; python app.py

# macOS/Linux:
python app.py
```

Open [http://localhost:5001](http://localhost:5001) in your browser.

---

## Running Tests

All 91 unit, integration, and golden regression tests run standalone:

```powershell
cd use-cases/AdhiShak3008/LatBuild
pytest -v
```

### Test Suites Included:
- `test_pdf_analyzer.py` — Column detection, valley histograms, heading classification, BBox geometry.
- `test_flow_mapper.py` — Section grouping, flow region construction, inline heading boundaries.
- `test_reflow_engine.py` — Typography measurement, region capacity, multi-paragraph distribution.
- `test_section_extractor.py` — Prose extraction, instruction construction, word count hints.
- `test_docx_bridge.py` — DOCX/HTML roundtrip conversion, citation preservation.
- `test_golden_pilotmaster.py` — End-to-end regression tests on 12-page IEEE paper `PilotMaster.pdf`.
- `test_comprehensive_reflow.py` — Transactional safety, rollback on overflow, multi-section atomicity.

---

## Supported Document Types

- **Supported**:
  - Digitally generated PDFs with selectable text
  - Multi-column and single-column academic papers (IEEE, ACM, Springer, etc.)
  - Reports, preprints, journals, and multi-page technical manuscripts
- **Explicit Exclusions**:
  - Scanned PDFs without selectable text (requires OCR preprocessing)
  - Password-protected or encrypted PDFs
  - Right-to-left scripts (RTL)

---

## License & Attribution

Built for the **SuperDocs Engineer Task — Round 2**.  
Created by **AdhiShak3008**.
