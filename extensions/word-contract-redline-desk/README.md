# SuperDocs Contract Redline Desk

A SuperDocs extension for reviewing proposed contract changes before they are applied.

## What it does

The Contract Redline Desk provides a review workflow for contract changes:

1. Loads a contract document.
2. Reviews the document against a configurable playbook.
3. Detects clauses that require changes.
4. Generates clause-level proposals containing:
   - Original text
   - Proposed replacement
   - Reason for the change
   - Review status
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
└── frontend/