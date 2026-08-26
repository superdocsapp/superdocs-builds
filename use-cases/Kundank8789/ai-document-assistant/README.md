# AI Document Assistant

An AI-powered document analysis application built for the SuperDocs Task 2 assignment.

The application allows users to upload multiple event documents, analyze their contents, generate a grounded Post-Event Impact Report, review AI-generated findings, approve or reject recommendations, and export the final report as a PDF.

## Features

- Upload multiple event documents
- PDF, TXT, DOCX, XLSX and XLS support
- Document content extraction
- Multi-document analysis
- AI-powered Post-Event Impact Report generation
- Executive summary
- Event overview
- Key outcomes
- Attendance insights
- Feedback insights
- Financial insights
- Document conflict detection
- AI recommendations
- Individual document summaries
- Human Review Queue
- Approve AI findings
- Reject AI findings
- Review status tracking
- SuperDocs async job processing
- Final report export
- PDF download
- Clear uploaded documents

## AI + Human Review Workflow

The application follows this workflow:

Upload Documents
        ↓
Analyze Documents
        ↓
Generate Post-Event Impact Report
        ↓
SuperDocs Async Processing
        ↓
Human Review Queue
        ↓
Approve / Reject AI Findings
        ↓
Review Complete
        ↓
Export Final Report as PDF

## Tech Stack

### Frontend

- React
- Vite
- JavaScript
- Tailwind CSS
- Lucide React

### Backend

- Node.js
- Express.js
- Multer
- pdf-parse
- Mammoth
- XLSX

### AI / Document Workflow

- SuperDocs API
- Groq API
- Async job processing
- Human-in-the-loop review workflow

## Project Structure

```text
ai-document-assistant/
├── src/
│   ├── components/
│   │   └── layout/
│   │       └── Sidebar.jsx
│   ├── pages/
│   │   ├── Documents.jsx
│   │   ├── EventData.jsx
│   │   ├── Overview.jsx
│   │   ├── ReviewQueue.jsx
│   │   └── Sponsors.jsx
│   ├── services/
│   │   └── superdocs.js
│   └── App.jsx
│
├── server/
│   ├── index.js
│   └── package.json
│
├── .gitignore
├── package.json
└── README.md

1. Clone the repository
git clone https://github.com/Kundank8789/superdocs-builds.git
2. Navigate to the project
cd superdocs-builds/use-cases/Kundank8789/ai-document-assistant
Frontend Setup

Install dependencies:

npm install

Start the frontend:

npm run dev

The frontend runs locally at:

http://localhost:5173
Backend Setup

Open another terminal:

cd server

Install dependencies:

npm install

Create a .env file:

GROQ_API_KEY=your_groq_api_key_here
SUPERDOCS_API_KEY=your_superdocs_api_key_here
PORT=5000

Start the backend:

npm run dev

The backend runs at:

http://localhost:5000
How to Use
Start the frontend and backend servers.
Open the application in the browser.
Navigate to the Documents page.
Upload one or more event documents.
Click Generate Report.
Wait for the SuperDocs async job to complete.
Open the Review Queue.
Review AI-generated findings.
Approve or reject each finding.
Once all findings are reviewed, click Export Final Report.
Download the generated PDF report.
Human Review Queue

The Review Queue provides a human-in-the-loop approval workflow for AI-generated findings.

Each finding contains:

Finding type
Title
AI-generated content
AI confidence
Review status
Approval/rejection decision
Reviewer note

Possible review states:

Pending
Approved
Rejected

The final report can be exported after all findings have been reviewed.

SuperDocs Integration

The application integrates with SuperDocs for:

Report generation
Async job processing
Job status polling
Proposed changes approval
Final document export

The frontend stores the SuperDocs session and job identifiers so that the Review Queue and export workflow can continue after report generation.

API Endpoints
Document APIs
Method	Endpoint	Description
GET	/	API status
POST	/api/upload	Upload documents
POST	/api/analyze	Analyze uploaded documents
POST	/api/clear	Clear uploaded documents
Human Review APIs
Method	Endpoint	Description
GET	/api/review	Get review queue
POST	/api/review/:id	Approve/reject finding
GET	/api/review/status	Get review status
SuperDocs APIs
Method	Endpoint	Description
POST	/api/superdocs/upload	Upload document through SuperDocs
POST	/api/superdocs/chat	Start report generation
GET	/api/superdocs/job/:jobId	Check async job status
POST	/api/superdocs/approve	Approve proposed changes
POST	/api/superdocs/export	Export final report
Environment Variables

The backend requires API credentials:

GROQ_API_KEY=your_groq_api_key_here
SUPERDOCS_API_KEY=your_superdocs_api_key_here
PORT=5000

Never commit .env files or API keys to GitHub.

Supported File Types
PDF (.pdf)
Text (.txt)
Word (.docx)
Excel (.xlsx, .xls)
Example Workflow

The application was tested using TechConnect Summit 2026 event documents.

The workflow successfully produced:

AI-generated post-event analysis
AI recommendations
Human review queue
Approved/rejected findings
Final PDF report
Submission

This project was built as part of the SuperDocs Task 2 build assignment.

Project location:

use-cases/Kundank8789/ai-document-assistant/

GitHub repository:

https://github.com/Kundank8789/superdocs-builds


### Then commit ONLY the README

After saving it:

```powershell
git add README.md
git commit -m "Update Task 2 documentation"
git push origin main
