# tej-thakar — SuperDocs Builds

Built by **Tej Thakar** for the SuperDocs Round 2 engineering task.

Execution log: see `WORKLOG.md` for the running step-by-step record across Task 1, Task 2, and follow-on work.

---

## Builds in this folder

### 1. Resume Bulk Normaliser (assigned — Band S2)
`resume-normaliser/`

Server-side service for job boards and ATS vendors. Normalises inbound resumes to a house schema at volume. Handles the messy real distribution of resume formats and reports failures honestly instead of producing silent garbage.

**Surfaces:** API, templates, export  
`POST /normalize` — up to 50 resumes, each through a SuperDocs HITL session

---

### 2. Claims Correspondence Generator (assigned — Band S2)
`claims-generator/`

Insurance claims teams drafting coverage and decision correspondence under review. Generates approval, partial-approval, denial, and information-request letters from structured claim data. Every letter sits in HITL approval until explicitly approved — nothing auto-sends.

**Surfaces:** API, Review, export  
`POST /generate` — single letter  
`POST /generate/batch` — up to 20 letters

---

### 3. Template Filler from a Record (open list — Band S1)
`template-filler/`

Operations, HR, or back-office coordinators at any templated-document shop. Accepts a template + JSON record and fills it. Fields the record does not answer become `[MISSING: field_name]` markers — never invented. Ten different records produce ten documents whose structure is identical to the template.

**Surfaces:** templates, chat, API, Review, export  
`POST /fill` — single template + record  
`POST /fill/batch` — up to 20

---

### 4. House-Style Enforcer (open list — Band S2)
`house-style-enforcer/`

Editorial leads, brand managers, and knowledge managers at agencies, publishers, or professional-services firms. Upload the real style guide (not a rules file). Audits any document against it in two lanes: language (terminology, banned phrasing, capitalisation) and formatting (heading levels, list style, table treatment). Every violation cites the style-guide passage it came from.

**Surfaces:** templates, search, chat, Review, export  
`POST /audit` — single style-guide + document  
`POST /audit/batch` — up to 20

---

## Setup

Each build is a standalone FastAPI service with its own `requirements.txt` and `.env.example`. No secrets are in this repository.

```bash
cd <build-folder>
pip install -r requirements.txt
cp .env.example .env   # add SUPERDOCS_API_KEY
uvicorn main:app --port <port>
```

---

## Credit line

This work was built for the SuperDocs Round 2 engineering task. The Task 1 private repository is at `github.com/tej-thakar/doctask-tej-thakar` (invite: o-kadam). All builds use the SuperDocs API surface; none are clones of SuperDocs itself.
