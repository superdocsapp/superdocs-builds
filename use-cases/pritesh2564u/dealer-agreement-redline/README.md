# Dealer Agreement Redline Desk

A contract-redlining workflow built with FastAPI, PostgreSQL, and the SuperDocs API.

The application compares a dealer-returned agreement against an approved master agreement and a negotiation playbook, detects deviations, classifies them, and routes them through a human-in-the-loop approval process before applying redlines and exporting the final document.

## Screenshots

![Dealer Agreement Redline - Screenshot 1](./screenshots/image1.png)

![Dealer Agreement Redline - Screenshot 2](./screenshots/image2.png)

![Dealer Agreement Redline - Screenshot 3](./screenshots/image3.png)

---

## Current Status

### Backend

- [x] SuperDocs API integration
- [x] API key configuration
- [x] Dealer agreement upload
- [x] Master agreement attachment upload
- [x] Negotiation playbook attachment upload
- [x] DOCX section extraction
- [x] Agreement deviation detection
- [x] Playbook-based classification
- [x] Redline review persistence
- [x] Finding persistence
- [x] Human approve/reject workflow
- [x] Apply approved redlines through SuperDocs
- [x] Export final DOCX
- [x] Duplicate apply protection
- [x] Review-state validation
- [x] Backend compilation verification
- [x] End-to-end workflow verification

### Frontend

- [ ] React frontend
- [ ] Review dashboard
- [ ] Review summary
- [ ] Finding cards
- [ ] Master vs dealer comparison
- [ ] Approve/reject controls
- [ ] Apply approved changes
- [ ] Export DOCX

---

## Architecture

```text
┌─────────────────┐
│     React UI     │
│    (Frontend)     │
└─────────┬────────┘
          │  HTTP
          ▼
┌─────────────────┐
│  FastAPI Backend  │
└─────────┬────────┘
          │
   ┌──────┴──────┐
   ▼             ▼
```

The frontend communicates only with the FastAPI backend.

The SuperDocs API key remains server-side and is never exposed to the browser.

## Workflow

```
Dealer Agreement
        │
        ▼
Create SuperDocs Session
        │
        ▼
Upload Dealer Agreement
        │
        ├── Master Agreement → Attachment
        │
        └── Negotiation Playbook → Attachment
        │
        ▼
Local Agreement Analysis
        │
        ├── Extract sections
        ├── Detect deviations
        └── Classify against playbook
        │
        ▼
Create Redline Review
        │
        ▼
Human Review
        │
        ├── Approve finding
        └── Reject finding
        │
        ▼
All Findings Reviewed
        │
        ▼
Apply Approved Findings
        │
        ▼
SuperDocs Updates Active Document
        │
        ▼
Export Final DOCX
```

---

## Redline Classification

Each detected deviation is classified into one of three categories:

```
PRE-APPROVED
ESCALATE
REFUSE
```

**PRE-APPROVED**
The requested change falls within the limits defined by the negotiation playbook.

**ESCALATE**
The requested change requires human review or approval.

**REFUSE**
The requested change exceeds the limits defined by the negotiation playbook and should not be accepted.

The classification is determined by the backend playbook classifier.

---

## Human Review

Every detected deviation is persisted as a redline finding.

The reviewer can make one of two decisions:

```
approve
reject
```

Only findings with:

```
decision = approve
```

are sent to SuperDocs for application.

Rejected findings are not applied to the document.

A finding cannot be reviewed more than once.

A completed or applied review cannot receive additional decisions.

---

## Review Status

A review progresses through the following states:

```
pending
   │
   ▼
in_review
   │
   ▼
completed
   │
   ▼
applied
```

**pending**
The review has been created but human review has not started.

**in_review**
At least one finding has been reviewed, but pending findings remain.

**completed**
All findings have received a human decision.

**applied**
All approved findings have been sent to SuperDocs and applied to the active document.

---

## Database

The backend uses PostgreSQL.

### `redline_reviews`

Stores the overall redline review.

Fields:

```
id
session_id
status
created_at
updated_at
```

### `redline_findings`

Stores individual deviations found during the analysis.

Fields:

```
id
review_id
section
master_text
dealer_text
deviation_type
similarity
classification
reason
counter_position
decision
created_at
```

Relationship:

```
RedlineReview
    │
    └── RedlineFinding
            ├── Finding 1
            ├── Finding 2
            ├── Finding 3
            └── ...
```

`review_id` references the parent review.

Deleting a review cascades to its findings.

---

## Backend Structure

```
backend/
├── app/
│   ├── api/
│   │   ├── __init__.py
│   │   ├── poc.py
│   │   ├── redline.py
│   │   └── superdocs.py
│   │
│   ├── db/
│   │   ├── base.py
│   │   ├── init_db.py
│   │   └── session.py
│   │
│   ├── models/
│   │   └── redline_review.py
│   │
│   ├── services/
│   │   ├── agreement_parser.py
│   │   ├── deviation_analyzer.py
│   │   ├── playbook_classifier.py
│   │   ├── redline_service.py
│   │   └── superdocs_redline.py
│   │
│   ├── superdocs/
│   │   ├── __init__.py
│   │   └── client.py
│   │
│   ├── config.py
│   └── main.py
│
├── .env
└── requirements.txt
```

`.env` is local-only and must never be committed.

---

## Test Data

The project contains three DOCX files used by the redline workflow:

```
test-data/
├── dealer-agreement.docx
├── master-agreement.docx
└── negotiation-playbook.docx
```

### Dealer Agreement

The dealer-returned agreement contains four relevant deviations:

```
Section 4.2  — Payment Terms
Section 7.1  — Agreement Term
Section 9.3  — Territory
Section 12.1 — Termination
```

### Master Agreement

The master agreement provides the approved baseline language.

### Negotiation Playbook

The negotiation playbook defines the allowed ranges and escalation/refusal rules.

---

## Current Example Analysis

For the provided test agreements, the backend produces:

```
Section 4.2 — Payment Terms
→ ESCALATE

Section 7.1 — Agreement Term
→ REFUSE

Section 9.3 — Territory
→ ESCALATE

Section 12.1 — Termination
→ REFUSE
```

Summary:

```json
{
    "total": 4,
    "pre_approved": 0,
    "escalate": 2,
    "refuse": 2
}
```

A human reviewer can approve the two escalation findings and reject the two refusal findings.

The resulting workflow is:

```
Payment Terms
→ APPROVE
→ APPLY

Agreement Term
→ REJECT
→ IGNORE

Territory
→ APPROVE
→ APPLY

Termination
→ REJECT
→ IGNORE
```

Only the two approved findings are sent to SuperDocs.

---

## SuperDocs Integration

The backend contains a dedicated `SuperDocsClient`.

The client supports:

- API key authentication
- API key verification
- Document upload
- Attachment upload
- Chat
- Human-in-the-loop approval
- Document export

### SuperDocs Authentication

The SuperDocs API uses the `Authorization` header:

```http
Authorization: Bearer sk_YOUR_API_KEY
```

The API key is stored in the backend environment:

```env
SUPERDOCS_API_KEY=sk_YOUR_API_KEY
```

The browser never receives this key.

### API Key Verification

SuperDocs provides:

```http
GET /v1/sessions
```

as a safe way to verify an API key.

The backend's SuperDocs client uses:

```
GET /v1/sessions
```

for verification.

A successful `200` response confirms that the API key is valid.

---

## Documents vs Attachments

SuperDocs provides two different ways to load files.

### Active Document

The dealer agreement is uploaded using:

```
/v1/documents/upload
```

This makes it the active editable document.

### Attachments

The master agreement and negotiation playbook are uploaded using:

```
/v1/attachments/upload
```

These provide reference material for the workflow.

The distinction is:

```
Dealer Agreement
→ Active editable document

Master Agreement
→ Reference attachment

Negotiation Playbook
→ Reference attachment
```

Attachments are useful as supporting context, while the document upload is used for the document that will actually be edited.

---

## SuperDocs Session

A unique SuperDocs session is created for each redline analysis.

The same `session_id` is persisted in `RedlineReview`.

This connects the application review to the SuperDocs active document:

```
RedlineReview
    │
    └── session_id
            │
            ▼
      SuperDocs Session
            │
            ▼
    Active Dealer Document
```

When `/apply` is called, the backend uses the stored session ID to modify the correct active SuperDocs document.

---

## SuperDocs Chat

The backend uses SuperDocs chat/document editing capabilities to apply approved counter-positions.

Only human-approved findings are passed to the application service.

The frontend does not communicate directly with the SuperDocs chat API.

---

## Human-in-the-Loop

The application has its own human review layer.

The workflow is:

```
AI / Backend Analysis
        │
        ▼
Redline Findings
        │
        ▼
Human Decision
    ┌───┴───┐
    │       │
Approve   Reject
    │       │
    ▼       ▼
  Apply   Ignore
```

SuperDocs also supports human-in-the-loop approval for document changes.

For the tested workflow, SuperDocs returned the applied edits as:

```
status: auto_approved
```

with:

```
requires_approval: null
pending_changes: null
```

Therefore, no additional SuperDocs approval call was required for the tested changes.

The application does not artificially call the SuperDocs approval endpoint when SuperDocs reports that there are no pending changes requiring approval.

---

## Applied Changes

For the tested review, two findings were approved.

SuperDocs returned:

```
2 sections edited, rest untouched
```

### Section 4.2 — Payment Terms

Original dealer language:

```
Dealer payments are due within 60 days of invoice.
```

Applied language:

```
Dealer payments are due within 30 days of invoice.
Any request for 60-day terms must be escalated for approval.
```

### Section 9.3 — Territory

Original dealer language:

```
Dealer shall operate within the assigned territory
and may sell to customers outside the territory.
```

Applied language:

```
Dealer shall operate within the assigned territory.
Expansion of territory is prohibited unless approved
through escalation.
```

The rejected findings remained unchanged.

---

## API Endpoints

### 1. Analyze Agreement

```http
POST /redline/analyze
```

Creates a SuperDocs session, uploads the required documents, analyzes the agreements, and persists a redline review.

Example:

```powershell
curl -X POST http://localhost:8000/redline/analyze
```

Response includes:

```
review_id
session_id
dealer_document
master_attachment
playbook_attachment
master_sections
dealer_sections
playbook_sections
deviations
summary
```

### 2. Get Review

```http
GET /redline/reviews/{review_id}
```

Returns:

- review status
- SuperDocs session ID
- timestamps
- all findings
- classification
- reason
- counter-position
- human decision

Example:

```powershell
curl http://localhost:8000/redline/reviews/REVIEW_ID
```

### 3. Decide Finding

```http
POST /redline/reviews/{review_id}/findings/{finding_id}/decision
```

Approve:

```json
{
    "decision": "approve"
}
```

Reject:

```json
{
    "decision": "reject"
}
```

The backend normalizes the decision using:

```
strip()
lower()
```

Therefore:

```
APPROVE
Approve
 approve
```

are normalized to:

```
approve
```

Only `approve` and `reject` are accepted.

### 4. Apply Approved Findings

```http
POST /redline/reviews/{review_id}/apply
```

This endpoint:

1. Loads the review.
2. Checks that the review has not already been applied.
3. Checks that no findings remain pending.
4. Loads all findings.
5. Passes approved findings to the SuperDocs redline service.
6. Applies approved changes to the active document.
7. Updates the review status to `applied`.

Example:

```powershell
curl -X POST http://localhost:8000/redline/reviews/REVIEW_ID/apply
```

A review cannot be applied twice.

Attempting to apply an already-applied review returns HTTP `409`.

### 5. Export

```http
GET /redline/reviews/{review_id}/export
```

Exports the currently applied SuperDocs document.

The generated file is:

```
dealer-agreement-redlined.docx
```

Example:

```powershell
curl -X GET http://localhost:8000/redline/reviews/REVIEW_ID/export -o dealer-agreement-redlined.docx
```

Export is blocked until the review status is:

```
applied
```

---

## Validation Rules

The backend currently validates:

- Required test files exist.
- Review exists before review operations.
- Finding exists before a decision is made.
- Finding belongs to the requested review.
- Finding cannot be decided twice.
- Completed reviews cannot receive new decisions.
- Applied reviews cannot receive new decisions.
- Pending findings prevent applying.
- Already-applied reviews cannot be applied again.
- Export requires an applied review.
- SuperDocs API errors are handled by the backend.
- Invalid decisions return HTTP `400`.
- Missing reviews/findings return HTTP `404`.
- Invalid workflow state returns HTTP `409`.
- SuperDocs failures return HTTP `502`.

---

## Error Responses

### Invalid Decision

```json
{
    "detail": "Decision must be either 'approve' or 'reject'."
}
```

HTTP: `400 Bad Request`

### Review Not Found

```json
{
    "detail": "Redline review not found"
}
```

HTTP: `404 Not Found`

### Finding Already Reviewed

```json
{
    "detail": "This finding has already been reviewed."
}
```

HTTP: `409 Conflict`

### Pending Findings

```json
{
    "detail": "2 finding(s) still require review."
}
```

HTTP: `409 Conflict`

### Review Already Applied

```json
{
    "detail": "This review has already been applied."
}
```

HTTP: `409 Conflict`

### Export Before Apply

```json
{
    "detail": "The review must be applied before exporting."
}
```

HTTP: `409 Conflict`

### SuperDocs Error

SuperDocs failures are returned as:

```
502 Bad Gateway
```

---

## Environment Variables

Create:

```
backend/.env
```

Example:

```env
DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5432/dealer_redline
SUPERDOCS_API_KEY=sk_YOUR_API_KEY
```

Never commit `.env`.

The `.env` file contains secrets and must remain local.

---

## Backend Setup

From the project root:

```powershell
cd backend
```

Create a virtual environment:

```powershell
python -m venv .venv
```

Activate it on Windows PowerShell:

```powershell
.\venv\Scripts\Activate.ps1
```

Install dependencies:

```powershell
pip install -r requirements.txt
```

Start the backend:

```powershell
uvicorn app.main:app --reload
```

The API runs at:

```
http://127.0.0.1:8000
```

Swagger documentation:

```
http://127.0.0.1:8000/docs
```

---

## Backend Verification

Python compilation can be checked with:

```powershell
python -m compileall app
```

A successful result finishes without syntax errors.

The current backend has been verified through the following workflow:

```
POST /redline/analyze
        ↓
GET /redline/reviews/{review_id}
        ↓
POST /redline/reviews/{review_id}/findings/{finding_id}/decision
        ↓
remaining_findings = 0
        ↓
POST /redline/reviews/{review_id}/apply
        ↓
status = applied
        ↓
GET /redline/reviews/{review_id}/export
        ↓
DOCX successfully exported
```

The duplicate-apply protection was also tested successfully.

Attempting to apply an already-applied review returns HTTP `409`.

---

## Backend Test Results

The following functionality has been tested successfully:

### Agreement Analysis

- ✓ Master agreement parsed
- ✓ Dealer agreement parsed
- ✓ Negotiation playbook parsed
- ✓ Deviations detected
- ✓ Deviations classified

### Database

- ✓ Redline review persisted
- ✓ Redline findings persisted
- ✓ Review retrieved
- ✓ Finding decisions persisted

### Human Review

- ✓ Finding approve
- ✓ Finding reject
- ✓ Pending finding count
- ✓ Review transitions to completed
- ✓ Duplicate decision prevented

### SuperDocs

- ✓ Dealer document uploaded
- ✓ Master attachment uploaded
- ✓ Playbook attachment uploaded
- ✓ Approved redlines applied
- ✓ Rejected redlines left unchanged
- ✓ Final document exported

### Workflow Protection

- ✓ Duplicate apply prevented
- ✓ Apply blocked while findings are pending
- ✓ Decision blocked after review completion
- ✓ Decision blocked after review application
- ✓ Export blocked before apply

---

## Frontend

The frontend is maintained separately from the backend.

The frontend directory is:

```
frontend/
```

The frontend will be built using React and TypeScript with Vite.

Planned structure:

```
frontend/
├── package.json
├── vite.config.ts
├── tsconfig.json
├── index.html
└── src/
    ├── main.tsx
    ├── App.tsx
    ├── api/
    │   └── redline.ts
    ├── components/
    │   ├── ReviewSummary.tsx
    │   ├── FindingCard.tsx
    │   └── ReviewActions.tsx
    └── types/
        └── redline.ts
```

### Planned Frontend Workflow

```
Start Review
      │
      ▼
POST /redline/analyze
      │
      ▼
Review Dashboard
      │
      ├── View summary
      ├── View master language
      ├── View dealer language
      ├── View classification
      ├── View reason
      └── View counter-position
      │
      ▼
Approve / Reject findings
      │
      ▼
All findings reviewed
      │
      ▼
Apply Approved Changes
      │
      ▼
Export DOCX
```

### Planned Frontend UI

```
┌────────────────────────────────────────────────────────────┐
│              Dealer Agreement Redline                        │
│        Review and approve contract changes                   │
├────────────────────────────────────────────────────────────┤
│                                                                │
│  Review Summary                                               │
│                                                                │
│   ┌─────┐   ┌──────────┐   ┌────────┐   ┌──────────┐        │
│   │  4  │   │    2     │   │   2    │   │    0     │        │
│   │Total│   │Escalate  │   │Refuse  │   │Reviewed  │        │
│   └─────┘   └──────────┘   └────────┘   └──────────┘        │
│                                                                │
├────────────────────────────────────────────────────────────┤
│                                                                │
│  Section 4.2 — Payment Terms                    ESCALATE     │
│                                                                │
│  Master:                                                      │
│  Dealer payments are due within 30 days of invoice.           │
│                                                                │
│  Dealer:                                                      │
│  Dealer payments are due within 60 days of invoice.           │
│                                                                │
│  Reason:                                                       │
│  Payment terms exceed the 45-day pre-approved limit.          │
│                                                                │
│  Counter-position:                                             │
│  Maintain the standard 30-day payment term or                 │
│  escalate the requested 60-day term for approval.              │
│                                                                │
│                    [ Reject ]  [ Approve ]                    │
│                                                                │
├────────────────────────────────────────────────────────────┤
│               [ Apply Approved Changes ]                      │
│               [ Export DOCX ]                                 │
└────────────────────────────────────────────────────────────┘
```

### Frontend API Flow

The frontend will consume the following backend APIs:

```
React
    │
    ├── POST /redline/analyze
    │
    ├── GET /redline/reviews/{review_id}
    │
    ├── POST /redline/reviews/{review_id}/findings/{finding_id}/decision
    │
    ├── POST /redline/reviews/{review_id}/apply
    │
    └── GET /redline/reviews/{review_id}/export
          │
          ▼
      FastAPI
          │
          ├── PostgreSQL
          │
          └── SuperDocs API
```

The frontend never calls:

```
https://api.superdocs.app
```

directly.

---

## Security

The SuperDocs API key is server-side only.

The frontend must never contain:

```
SUPERDOCS_API_KEY
```

The frontend must never make direct requests to:

```
https://api.superdocs.app
```

All SuperDocs operations must go through the FastAPI backend.

The `.env` file must never be committed to Git.

---

## Git Ignore

The repository should ignore local environment files and generated files:

```gitignore
# Environment
.env
.env.*

# Python
__pycache__/
*.py[cod]
.venv/
venv/

# Node
node_modules/
dist/

# IDE
.vscode/
.idea/

# Generated export
dealer-agreement-redlined.docx
```

Do not use a blanket:

```gitignore
*.docx
```

rule.

The test DOCX files under `test-data/` are required project files and should remain tracked:

```
test-data/
├── dealer-agreement.docx
├── master-agreement.docx
└── negotiation-playbook.docx
```

---

## Project Directory

The current project structure is:

```
dealer-agreement-redline/
│
├── backend/
│   ├── app/
│   ├── .env
│   └── requirements.txt
│
├── frontend/
│
├── test-data/
│   ├── dealer-agreement.docx
│   ├── master-agreement.docx
│   └── negotiation-playbook.docx
│
├── .gitignore
└── README.md
```

---

## Development Notes

This project is a focused proof of concept for the dealer-agreement redline workflow.

The backend currently provides the complete functional workflow:

```
Analyze
   ↓
Persist Review
   ↓
Review Findings
   ↓
Approve / Reject
   ↓
Apply Approved Changes
   ↓
Export DOCX
```

The backend is complete and tested before starting frontend implementation.

The frontend will consume the existing backend APIs and provide the user-facing review interface.

The SuperDocs API key remains completely server-side.

---

## Current Milestone

### Task 2 Backend

```
STATUS: COMPLETE
```

Completed:

- ✓ SuperDocs integration
- ✓ Document uploads
- ✓ Attachment uploads
- ✓ Agreement parsing
- ✓ Deviation analysis
- ✓ Playbook classification
- ✓ PostgreSQL persistence
- ✓ Human review
- ✓ Approve/reject decisions
- ✓ Apply approved changes
- ✓ Export DOCX
- ✓ Workflow validation
- ✓ Duplicate apply protection
- ✓ Backend verification

### Next

- Build the React frontend (dashboard, finding cards, comparison view, approve/reject controls, apply and export actions).
