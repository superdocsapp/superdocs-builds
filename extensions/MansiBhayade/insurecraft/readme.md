# InsureCraft — AI Insurance Policy Builder & Reviewer

InsureCraft is a Microsoft Word add-in for building, reviewing, modifying, approving, and exporting insurance policy documents using the SuperDocs API.

It combines a Word task pane, FastAPI backend, and SuperDocs to provide a human-in-the-loop insurance document workflow.

## Key Features

- **Policy Builder** — Create insurance policies from structured inputs such as insured name, policy number, coverage limits, deductible, dates, and endorsements.
- **Policy Review** — Review an existing Word policy using natural-language instructions.
- **AI-Proposed Changes** — SuperDocs identifies and presents document changes before they are applied.
- **Human Approval** — Users can approve or reject proposed changes.
- **Endorsement Builder** — Draft policy endorsements/amendments using existing policy wording.
- **Async Processing** — Track SuperDocs jobs and approval stages.
- **Word Integration** — Read and update the active Microsoft Word document using Office.js.
- **DOCX Export** — Export the final processed document.

## Architecture & Workflow

Microsoft Word
     │
     │ Office.js
     ▼
Word Task Pane
     │
     │ HTTP / REST
     ▼
FastAPI Backend
     │
     │ SuperDocs API
     ▼
SuperDocs
     │
     ▼
AI Document Processing
     │
     ▼
Proposed Changes
     │
     ▼
Human Approval / Rejection
     │
     ▼
Updated Policy
     │
     ▼
Insert into Word
     │
     ▼
Export DOCX

## SuperDocs Features Used

InsureCraft integrates with the SuperDocs API for document processing, editing, approvals, job tracking, and export.

### SuperDocs API Endpoints Used

| SuperDocs Endpoint | Method | Purpose |
|---|---|---|
| `/v1/sessions` | GET | Check and retrieve SuperDocs sessions |
| `/v1/chat` | POST | Synchronous document editing and processing |
| `/v1/chat/async` | POST | Start asynchronous document review/editing jobs |
| `/v1/sessions/{session_id}/jobs` | GET | Track asynchronous job status |
| `/v1/jobs/{job_id}` | GET | Retrieve individual job information |
| `/v1/chat/{session_id}/approve` | POST | Approve or reject proposed document changes |
| `/v1/attachments` | POST | Upload documents to SuperDocs |
| `/v1/documents/export` | POST | Export the processed document as DOCX |

### SuperDocs Capabilities Used

- **Chat-based document editing** — natural-language instructions are used to modify insurance policies.
- **Asynchronous document processing** — policy reviews and endorsement generation are processed as background jobs.
- **Document context** — the current Word document HTML is sent to SuperDocs for analysis and editing.
- **Human-in-the-loop approval** — proposed changes are returned for user approval or rejection before being applied.
- **Job tracking** — the application polls SuperDocs for processing status and completion.
- **Document change tracking** — SuperDocs returns proposed and completed document changes.
- **Document export** — the final processed document can be exported as a DOCX file.
- **Session management** — SuperDocs sessions are used to maintain the document workflow.

## How to Run SuperDocs

### Prerequisites

* Python 3.10+
* Node.js and npm
* Microsoft Word
* SuperDocs API key

### 1. Clone the Repository

```bash
git clone <your-repository-url>
```

### 2. Configure Environment Variables

Create a `.env` file in the backend directory:

```bash
SUPERDOCS_API_KEY=your-superdocs-api-key
SUPERDOCS_BASE_URL=[https://api.superdocs.app](https://api.superdocs.app)
```

### 3. Install Backend Dependencies

Create a virtual environment:
```bash
python -m venv .venv
```

Activate it on Windows:
```bash
.venv\Scripts\activate
```

Install requirements.txt
```bash
pip install -r requirements.txt
```

### 4. Load frontend and backend

Start fast API Backend
```bash
uvicorn app.main:app --reload --port 5000
```

5. Start the Word Add-in
Navigate to the Word add-in directory:
Install the required Node dependencies:
```bash
npm install
```

Start the add-in:
```bash
npm start
```

### Open Microsoft Word and load the InsureCraft task pane to begin

## Demo
https://drive.google.com/file/d/1tQ7nfYbQ0XPC7dUdqAxo1Zo0mJVSVBY1/view?usp=sharing


