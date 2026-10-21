# Construction Contract Pack

Built by Shivansh Kalra for the SuperDocs task.

Generates a set of standard-form-shaped construction documents that share
one project and correctly cross-reference each other: a Master Subcontract
Agreement, a Change Order, a Request for Information, and a Payment
Application. The Change Order and Payment Application each cite the exact
Article number *and title* from the base agreement that governs them --
verified programmatically against the base agreement's own text, not just
asserted.

All content is synthetic (a fictional general contractor, subcontractor,
and renovation project) built specifically for this task -- no real
parties, project, or figures.

## What it does

1. Uploads a Master Subcontract Agreement (AIA-shaped: numbered Articles
   covering scope, payment terms, changes in the work, termination, etc.)
   into a SuperDocs session.
2. Opens three more documents into the *same* session -- a Change Order, an
   RFI, and a Payment Application -- so SuperDocs can read the base
   agreement's real content while drafting each one.
3. Drafts each document via targeted chat instructions that explicitly say
   "read the open Master Agreement and cite its real Article number and
   title -- don't guess it."
4. Exports all four as `.docx` files.
5. Verifies the result: extracts the real Article numbers for "Changes in
   the Work" and "Payments" from the base agreement's own text, then checks
   the exported Change Order and Payment Application actually cite them.

## How to run it

```bash
python -m venv .venv
.venv/Scripts/activate   # or source .venv/bin/activate on macOS/Linux
pip install -r requirements.txt
cp .env.example .env     # then set SUPERDOCS_API_KEY
python build.py
```

Requires a SuperDocs account and API key (Settings &rarr; API Keys &rarr;
Create API Key at use.superdocs.app). Exported files land in `output/`
(gitignored). A full run costs a small number of operations -- three chat
edits and four exports; exports don't cost operations, only the chat/search
calls do.

## SuperDocs features used

- **Document upload** (`POST /v1/documents/upload`, multipart) with
  `open_mode` to build a real multi-document session (`new_focused` /
  `background`), not just one document at a time
- **Chat / async edit** (`POST /v1/chat/async`) targeted at a specific
  `document_id` within that session, so each derived document gets drafted
  against the base agreement's real content
- **Human-in-the-loop approval** (`POST /v1/chat/{session_id}/approve`,
  `approval_mode: "ask_every_time"`) -- see the note below on a real
  limitation found while exercising this
- **Export** (`POST /v1/documents/export`, `.docx`) per document, via each
  document's fetched HTML rather than the session as a whole -- export
  doesn't support pulling one document out of a multi-document session by
  ID, so this reads each document's HTML by its durable ID and exports that
  directly

## A real bug found while building this

`approval_mode: "ask_every_time"` works correctly and produces a genuine
`awaiting_approval` state with real `pending_changes` -- confirmed with an
isolated single-document test. But when the chat request also includes an
explicit `document_id` (required to target one specific document inside a
multi-document session), the approval gate is silently skipped and the
edit auto-applies instead, even though `ask_every_time` was requested.
Reproduced twice, isolated to exactly that one parameter combination.

This build's actual drafting calls hit that combination (targeting one of
four open documents), so those specific calls auto-applied rather than
genuinely pausing for approval. The approve endpoint itself was verified
working correctly, independently, in a single-document session -- this
write-up doesn't claim more than what was actually observed.

## Files

- `content/base_agreement.html` -- the authored base agreement (its Article
  numbers are the ground truth the verification step checks against)
- `content/*_stub.html` -- minimal title-only stubs opened as the other
  three documents, then drafted via chat
- `build.py` -- the full upload -> multi-document session -> chat ->
  approve -> export -> verify flow
- `output/` -- exported `.docx` files (gitignored; run `build.py` to
  regenerate)
