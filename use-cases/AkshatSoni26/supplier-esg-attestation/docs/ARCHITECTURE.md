# SupplyGuard: Architecture & System Design

> **System:** Supplier ESG & Responsible-Sourcing Attestation Engine  
> **Author:** Akshat Soni | Full-Stack AI Engineer  
> **Assigned Build:** S2 (Responsible Sourcing & Supplier Attestation)

---

## 1. End-to-End System Architecture

```mermaid
flowchart TD
    subgraph Frontend ["Frontend Client (Next.js 16 + React 19 + Tailwind CSS + Turbopack)"]
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

---

## 2. 4-Stage Attestation Lifecycle State Machine

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

---

## 3. Database Entity Relationship Diagram (ERD)

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
