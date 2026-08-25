# SuperDocs Contract Redline Desk

A SuperDocs extension for reviewing proposed contract changes before they are applied.

## What it does

The Contract Redline Desk provides a review workflow for contract changes:

1. Loads a contract document.
2. Reviews the document against a configurable playbook.
3. Detects clauses that require changes.
4. Generates clause-level proposals containing:

   * Original text
   * Proposed replacement
   * Reason for the change
   * Review status
5. Presents proposals in a review interface.
6. Allows the reviewer to approve or reject each proposal.
7. Prevents rejected proposals from being applied.
8. Allows the reviewed result to be exported as a DOCX.

The human approval step is intentionally kept in the workflow so proposed changes are not automatically accepted.

## Project structure

```text
word-contract-redline-desk/
├── app.py
├── redline_engine.py
├── superdocs_client.py
├── test_redline.py
├── requirements.txt
├── README.md
├── data/
├── tests/
├── frontend/
└── word-addin/
    ├── manifest.xml
    └── src/
        ├── taskpane.html
        └── taskpane.js
```

## Workflow

```text
Contract DOCX
     ↓
Redline Engine
     ↓
Proposed Changes
     ↓
Human Review
   ↙       ↘
Approve   Reject
   ↓         ↓
Apply      Ignore
   \         /
    ↓       ↓
   Export reviewed DOCX
```

A proposal remains `pending` until the reviewer explicitly approves or rejects it.

The export endpoint blocks the operation while any proposal is still pending.

## Human approval gate

The system maintains three proposal states:

* `pending` — waiting for reviewer decision
* `approved` — change can be applied
* `rejected` — change must not be applied

The backend checks for pending proposals before exporting.

If any proposal is still pending, the export request is rejected:

```text
Pending proposals must be approved or rejected before export.
```

This ensures that unreviewed changes cannot accidentally make it into the exported document.

## Review state

Reviewer decisions are persisted in:

```text
data/review_state.json
```

This allows the application to retain review decisions when the backend restarts.

Example proposal:

```json
{
  "id": 68,
  "clause": "Limitation of Liability",
  "paragraph_index": 5,
  "before": "The liability of each party under this Agreement shall be unlimited.",
  "after": "The liability of each party under this Agreement shall be limited to the total fees paid under this Agreement.",
  "reason": "Liability should be capped at the total fees paid under the agreement.",
  "status": "approved"
}
```

## API

The FastAPI backend provides the following main endpoints:

| Endpoint         | Method | Purpose                             |
| ---------------- | ------ | ----------------------------------- |
| `/`              | GET    | Check application status            |
| `/review`        | GET    | Load contract review proposals      |
| `/decision`      | POST   | Approve or reject a proposal        |
| `/export`        | POST   | Export the reviewed DOCX            |
| `/taskpane.html` | GET    | Serve the Word task pane            |
| `/taskpane.js`   | GET    | Serve the Word task pane JavaScript |

### Approve a proposal

```json
{
  "proposal_id": 68,
  "decision": "approved"
}
```

### Reject a proposal

```json
{
  "proposal_id": 68,
  "decision": "rejected"
}
```

## Running locally

Create and activate the Python environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Install dependencies:

```powershell
pip install -r requirements.txt
```

Start the FastAPI server:

```powershell
uvicorn app:app --reload --port 8000
```

The backend runs at:

```text
http://localhost:8000
```

The review endpoint is available at:

```text
http://localhost:8000/review
```

The Word task pane is served at:

```text
http://localhost:8000/taskpane.html
```

## Testing

The workflow can be tested by:

1. Starting the FastAPI backend.
2. Loading the review interface.
3. Checking the generated proposal.
4. Leaving a proposal as `pending`.
5. Attempting to export.
6. Confirming that export is blocked.
7. Approving or rejecting the proposal.
8. Exporting the reviewed DOCX.
9. Checking that only approved changes are applied.

The project also contains the existing redline tests under `test_redline.py` and `tests/`.

## Technology stack

* Python
* FastAPI
* Pydantic
* python-docx
* HTML
* JavaScript
* Microsoft Word Task Pane Add-in
* JSON

## Design goal

The extension demonstrates a human-in-the-loop document workflow.

Instead of automatically modifying a contract, the system:

**detects → proposes → waits for human decision → applies approved changes → exports the result.**

This provides a clear review boundary and makes proposed document changes traceable before they are applied.
