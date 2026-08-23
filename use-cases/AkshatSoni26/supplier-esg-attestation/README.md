# SupplyGuard — Supplier ESG Attestation & Responsible-Sourcing Compliance Engine

> *Built for the SuperDocs Full-Stack AI Engineer Task (Assigned Build S2: Responsible-Sourcing & Supplier Attestation)*

An automated, audit-ready compliance intelligence platform built on the **SuperDocs API & MCP surface**. The system manages the complete annual supplier ESG attestation lifecycle: issuing localized tier-specific questionnaires and codes of conduct, normalizing multi-format responses into a standardized schema, enforcing human-in-the-loop review gates, automatically drafting evidence-quoted deficiency notices, and reconciling aggregate risk profile charts.

---

## 🎬 Live Product Walkthrough Demo

▶️ **Watch the 3-Minute Video Demo on Loom:** [SuperDocs Supplier ESG Attestation Engine Demo](https://www.loom.com/share/4ee46470abbf47a1a28bf1d77eeb285a)

---

## 📁 Declared Domain & Multi-Tier Regulatory Scope

| Supplier Tier | Mandatory Audit Scope | Regulatory Annexes & Frameworks |
|:---|:---|:---|
| **Tier 1 (Strategic)** | Scope 1, 2, and 3 GHG accounting, ISO 14001 Environmental Management, Sub-Tier BOM Provenance | **EU CSRD / CSDDD / REACH** (Europe) |
| **Tier 2 (Manufacturing)** | Electricity/Fuel Consumption, Hazardous Chemical Waste, Statutory 60h Workweek Caps, Recruitment Fee Prohibition | **APAC Labor & Migrant Rights (ILO C001/C029)** (Asia-Pacific) |
| **Tier 3 (Commodities)** | Statutory EPA Discharge Permits, Clean Transport Fleet Logistics, Anti-Bribery & Corruption Pledge | **US UFLPA & Conflict Minerals** (North America) |

* **Accepted Response Formats:** `.pdf`, `.docx`, `.txt`, `.json`
* **Extraction Strategy:** Memory-safe stream parsing without buffering entire large files into RAM.

---

## 🛠️ Complete Technology Stack

* **Backend Framework:** **FastAPI** (Python 3.12, strict Pydantic v2 schemas, zero `Any`/`dict` loose typing).
* **Evaluator Architecture:** **Decomposed Single-Responsibility Sub-Services** (`EnvironmentalEvaluator`, `SocialEvaluator`, `GovernanceEvaluator`, `ESGScoringCalculator`).
* **Document Templating & PDF Generation:** **Jinja2** (dynamic questionnaire & deficiency notice markdown compilation) + **ReportLab** (audit-grade vector PDF exports).
* **SuperDocs Integration:** **SuperDocs API & MCP Surface** (4-Step Contract: Upload $\rightarrow$ Chat/Edit $\rightarrow$ Approve $\rightarrow$ Export with 2-Step JSON string parsing).
* **Database Layer:** **Async SQLAlchemy + SQLite / PostgreSQL** (Suppliers, Attestations, Findings, Letters).
* **Frontend UI:** **Next.js 16 (Turbopack) + React 19** (Tailwind CSS, high-contrast dark theme, Recharts visualizations, custom React hooks).

---

## 📸 System Architecture & Mermaid Diagrams

<details open>
<summary><b>📊 End-to-End System Pipeline (Click to Expand / Collapse)</b></summary>

```mermaid
flowchart TD
    subgraph Frontend ["Next.js App Router (React 19 + Tailwind CSS + Recharts)"]
        Nav["🧭 Top Navbar with 3-Tab Switcher\n(Supplier Operations | Executive Analytics | Compliance Audit Hub)"]
        Tab1["🏢 Tab 1: Supplier Directory Table & Actions\n(Issue Package, Upload Response, Review Gate, Deficiency Letter)"]
        Tab2["📊 Tab 2: Executive Analytics Charts\n(Risk Profile Donut, Tier Stacked Bars, Pillar Progress Gauges)"]
        Tab3["📑 Tab 3: Compliance & Legal Evidence Hub\n(Verbatim Evidence Quotes, Severity Breakdown, PDF Trigger)"]
        Hooks["⚡ Custom Hooks Layer\n(useAttestationCycle | useProgrammeReport)"]
        Config["⚙️ Centralized Config & Dynamic URL Builder\n(NEXT_PUBLIC_API_URL / Zero Hardcoded URLs)"]
    end

    subgraph API_Gateway ["FastAPI Backend (Python 3.12 + Async SQLAlchemy + Strict Pydantic)"]
        Router["FastAPI REST Endpoints (/api/v1)"]
        
        subgraph Evaluators ["Decomposed Single-Responsibility Evaluators (SRP)"]
            EE["🌿 EnvironmentalEvaluator\n(Scope 1-3 GHG, ISO 14001, Clean Energy %)"]
            SE["👥 SocialEvaluator\n(ILO Working Hours, Overtime Caps, Recruitment Fees)"]
            GE["🏛️ GovernanceEvaluator\n(Anti-Bribery, Whistleblower Hotline, Sub-Tier BOM)"]
            SC["⚖️ ESGScoringCalculator\n(Pillar Scores, Risk Indices, Honest Narrative)"]
        end

        subgraph CoreServices ["Orchestration & Document Services"]
            Issuance["📝 IssuanceService (Jinja2 Tier/Region Templates)"]
            Ingestion["📥 IngestionService (Stream-Safe PDF/DOCX/TXT Parsing)"]
            Norm["🔄 NormalizationService (Quote Extractor & Evaluator Orchestrator)"]
            FollowUp["✉️ FollowUpService (Deficiency Letters with Verbatim Quotes)"]
            Aggregation["📈 AggregationService (Cross-Tier Reconciliation)"]
            DocExport["📑 DocumentExportService (ReportLab Multi-Page Vector PDF)"]
            SD_Client["🤖 SuperDocsClientService (4-Step Contract & 2-Step JSON Parse)"]
        end
        
        DB[("Database (SQLite / PostgreSQL)\n(Suppliers, Attestations, Findings, Letters)")]
    end

    subgraph External ["SuperDocs Surface"]
        SD_Platform["SuperDocs API / MCP Surface\n(Upload -> Chat/Edit -> Approve -> Export)"]
    end

    Frontend <--> Router
    Router --> CoreServices
    CoreServices --> Evaluators
    CoreServices <--> DB
    DocExport --> SD_Client
    SD_Client <--> SD_Platform
```

</details>

<details>
<summary><b>🔄 4-Stage Attestation Lifecycle State Machine (Click to Expand)</b></summary>

```mermaid
stateDiagram-v2
    [*] --> NOT_ISSUED: Seed / Register Base Suppliers
    
    NOT_ISSUED --> ISSUED: Stage 1 (Issue Tailored Questionnaire Package)
    note right of ISSUED: Compiles Tier 1/2/3 scopes + EU CSRD/APAC Labor/US UFLPA Annexes
    
    ISSUED --> SUBMITTED: Stage 2 (Supplier Uploads PDF / DOCX / TXT)
    note right of SUBMITTED: Memory-safe stream parsing without full RAM buffering
    
    SUBMITTED --> NORMALIZED: Automated Data Extraction & Exact Quote Citation
    note right of NORMALIZED: Decomposed Evaluators calculate E, S, G sub-scores & extract verbatim evidence
    
    NORMALIZED --> UNDER_REVIEW: Stage 3 (Human Review Gate Triggered)
    
    UNDER_REVIEW --> APPROVED: Human Compliance Officer Approves (0 Gaps Clean)
    UNDER_REVIEW --> FOLLOW_UP_REQUIRED: Human Officer Approves Identified Shortfalls
    
    FOLLOW_UP_REQUIRED --> DEFICIENCY_NOTICE_SENT: Stage 4 (Generate Letter Quoting Exact Supplier Words)
    DEFICIENCY_NOTICE_SENT --> APPROVED: Supplier Resolves 30-Day Corrective Action Audit
    
    APPROVED --> [*]: Executive Programme Report PDF Generated
```

</details>

<details>
<summary><b>🗄️ Database Entity Relationship Diagram ERD (Click to Expand)</b></summary>

```mermaid
erDiagram
    SUPPLIER ||--o{ ATTESTATION_CYCLE : participates_in
    ATTESTATION_CYCLE ||--o| ASSESSMENT : evaluated_by
    ASSESSMENT ||--o{ FINDING : contains
    ATTESTATION_CYCLE ||--o| FOLLOW_UP_LETTER : generates

    SUPPLIER {
        string id PK
        string name
        string code UK
        string tier "TIER_1_STRATEGIC | TIER_2_MANUFACTURING | TIER_3_COMMODITY"
        string region "EU | APAC | NORTH_AMERICA"
        string country
        string primary_contact_email
        timestamp created_at
    }

    ATTESTATION_CYCLE {
        string id PK
        string supplier_id FK
        int cycle_year
        string status "NOT_ISSUED | ISSUED | SUBMITTED | NORMALIZED | UNDER_REVIEW | APPROVED | FOLLOW_UP_REQUIRED"
        string issued_document_id
        string response_document_id
        string response_format "PDF | DOCX | TXT"
        timestamp submitted_at
        timestamp normalized_at
    }

    ASSESSMENT {
        string id PK
        string attestation_id FK
        float overall_risk_score "0.0 - 100.0"
        string risk_tier "LOW | MEDIUM | HIGH | CRITICAL"
        float environmental_score
        float social_score
        float governance_score
        text summary_markdown
        boolean is_approved
        string approved_by
        timestamp approved_at
    }

    FINDING {
        string id PK
        string assessment_id FK
        string pillar "ENVIRONMENTAL | SOCIAL | GOVERNANCE"
        string severity "LOW | MEDIUM | HIGH | CRITICAL"
        string standard_clause
        text shortfall_summary
        text supplier_exact_quote
        string source_location
        text recommended_action
        string review_decision "PENDING | ACCEPTED | REJECTED"
    }

    FOLLOW_UP_LETTER {
        string id PK
        string attestation_id FK
        text letter_markdown
        string recipient_email
        timestamp generated_at
        timestamp sent_at
    }
```

</details>

*Raw diagram source files are also preserved in [`mermaid/`](mermaid/).*

---

## 🌟 What Strong Looks Like (Rubric Achievements)

1. **Multi-Format Normalization into One Unified Shape**:
   - Ingests supplier returns across PDF, Word (`.docx`), plain text, and JSON without loading entire files into memory.
   - Normalizes submissions into a strictly typed `NormalizedAssessmentSchema` with Environmental, Social, and Governance sub-scores (0–100) and risk tier classifications.
2. **Surgical Evidence Quotes in Follow-Up Letters**:
   - Every flagged shortfall finding automatically extracts and quotes the **supplier's exact verbatim submitted statement** (e.g., *"We currently do not track Scope 2 indirect emissions from electricity consumption"*).
3. **Mathematical Reconciliation in Aggregate Reports**:
   - Executive dashboard charts (Risk Profile Donut, Stacked Tier Bar Chart, Pillar Compliance Averages) mathematically reconcile with individual supplier assessment records.
4. **Honest Zero-Finding Reports**:
   - Compliant suppliers (e.g., `Nordic CleanTech Solutions AB`) receive an honest report of **0 findings**, proving the system never hallucinates defects.
5. **SuperDocs 4-Step Contract & Two-Step JSON String Parsing**:
   - Strictly implements `Upload` $\rightarrow$ `Chat/Edit` $\rightarrow$ `Approve` $\rightarrow$ `Export`.
   - Correctly unpacks double JSON string-encoded proposed change payloads from SuperDocs to avoid undefined diff cards.

---

## 🚀 Quickstart & Makefile Automation

```bash
# 1. Install all dependencies (Backend uv + Frontend bun/npm)
make install

# 2. Reset Database & Seed Fresh Suppliers Across All Lifecycle Stages
make reset-db

# 3. Start Backend (FastAPI on Port 8001)
make backend

# 4. Start Frontend (Next.js on Port 3031)
make frontend
```
*The frontend dashboard opens at `http://localhost:3031`.*

---

## 🧪 Automated Testing Suites (27 Backend + 14 Frontend Tests)

All tests execute in milliseconds with in-memory SQLite and mock SuperDocs fallback:

```bash
# Run all tests (Backend + Frontend)
make test-all

# Or run separately:
make test-backend   # 27 pytest unit tests (~0.4s)
make test-frontend  # 14 bun unit tests (~0.3s)
```

---

## ⚖️ Self-Reported Limitations & Future Roadmap (TODOs)

- [ ] **OCR Pre-Processing for Scanned/Raster PDFs:** Currently extracts text using PyPDF stream parsing; scanned raster-only PDFs fall back to raw text layers. In production, an upstream vision OCR worker handles image scans.
- [ ] **Server-Side Dynamic SVG Chart Rasterization in PDFs:** The executive dashboard renders interactive Recharts; the exported ReportLab PDF renders structured typography and summary tables. Native CairoSVG chart vectorization is earmarked for v1.1.
- [ ] **Bi-Directional Supplier Portal Webhook:** Direct integration with supplier ERP systems (SAP Ariba, Coupa) to auto-receive supplier returns via webhook triggers.
