# School Improvement Plan Drafter 🏫📊

An automated drafting assistant for education administrators to build, monitor, and export mandated school improvement plans.

## Features Used
- **Durable Sessions (`/v1/sessions/init`):** Holds multi-document context in step-by-step turns.
- **AI Chat Editor (`/v1/chat`):** Performs inline modifications of needs assessment data, targets, and progress status.
- **Multi-Document Tabs:** Holds both the primary improvement plan and the derived board progress report in separate tabs under one session.
- **Fidelity Export (`/v1/documents/export`):** Exports the final plan to a styled PDF with data tables intact.

## Quickstart

### 1. Set environment variable
```bash
export SUPERDOCS_API_KEY=your-api-key-here
```

### 2. Run the script using project python virtualenv
```bash
../../venv/bin/python3 draft_plan.py
```

This will initialize a session, upload the baseline prior plan, draft the new 2026 plan incorporating current assessment metrics, execute a mid-year progress update, and print the resulting document export download link!
