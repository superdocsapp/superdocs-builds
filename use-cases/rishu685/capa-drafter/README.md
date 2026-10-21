# Corrective Action Plan (CAPA) Drafter ⚙️🛡️

A compliance drafting utility for manufacturing quality teams to document defects and walk through root-cause analysis using the 8D methodology.

## Features Used
- **Durable Sessions (`/v1/sessions/init`):** Builds a structured 8D outline as baseline context.
- **AI Chat Editor (`/v1/chat`):** Automatically structures raw incident reports, root causes, corrective actions, and prevention logs into standard sections.
- **Fidelity Export (`/v1/documents/export`):** Exports the audit-ready CAPA report to PDF with formatting preserved.

## Quickstart

### 1. Set environment variable
```bash
export SUPERDOCS_API_KEY=your-api-key-here
```

### 2. Run the script using project python virtualenv
```bash
../../venv/bin/python3 draft_capa.py
```

This will initialize a session, generate the 8D template structure, populate the defect & containment details (D1-D4), add validation & prevention procedures (D5-D8), and print the final document export download link!
