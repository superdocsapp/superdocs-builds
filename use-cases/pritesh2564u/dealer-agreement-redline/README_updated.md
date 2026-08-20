# Dealer Agreement Redline Desk

A contract-redlining workflow built with FastAPI, PostgreSQL, and the SuperDocs API.

The application compares a dealer-returned agreement against an approved master agreement and a negotiation playbook, detects deviations, classifies them, and routes them through a human-in-the-loop approval process before applying redlines and exporting the final document.

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

The frontend is implemented with React, TypeScript, Vite, Tailwind CSS, and Lucide React icons.

It provides the complete user-facing workflow:

- Dynamic upload of dealer, master, and playbook DOCX files
- Review summary
- Finding classification badges
- Collapsible finding cards
- Master vs dealer comparison
- Reason and counter-position display
- Approve/reject controls
- Review progress
- Apply approved changes
- Export final DOCX
- Loading, success, and error states
- Fixed header
- Responsive layout
- Lucide icons

### Frontend Structure

```text
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
    │   ├── DocumentUpload.tsx
    │   ├── EmptyState.tsx
    │   ├── FindingCard.tsx
    │   ├── FindingList.tsx
    │   ├── Header.tsx
    │   └── SuccessMessage.tsx
    └── types/
        └── redline.ts
```

### Frontend Workflow

```text
Upload Documents
      │
      ▼
POST /redline/analyze
      │
      ▼
Review Dashboard
      │
      ├── Summary
      ├── Classification
      ├── Master language
      ├── Dealer language
      ├── Reason
      └── Counter-position
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

### Finding UX

Findings are collapsed by default so reviews with many deviations remain compact.

The collapsed card shows the finding number, section, classification, and decision status. Expanding a card reveals the master text, dealer text, reason, counter-position, and approve/reject actions.

### Frontend Development

From the frontend directory:

```powershell
npm install
npm run dev
```

The Vite development server runs at:

```text
http://localhost:5173
```

Production build:

```powershell
npm run build
```

The frontend communicates only with the FastAPI backend. It never receives or exposes the SuperDocs API key.

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

### Task 2

```text
STATUS: COMPLETE
```

Completed:

- ✓ SuperDocs integration
- ✓ Dynamic dealer/master/playbook uploads
- ✓ Dealer document loaded into the SuperDocs session
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
- ✓ Responsive React frontend
- ✓ Collapsible findings
- ✓ Fixed header
- ✓ Lucide icons
- ✓ User-friendly loading/success/error states
- ✓ End-to-end workflow verification
- ✓ Backend compilation verification

The complete Task 2 workflow is implemented and tested.
