# Add accessible-document and HACCP use-case builds

## Author

Anjali Yadav

## Summary

This PR adds both assigned Task 2 builds:

- `accessible-doc-kit` remediates structural accessibility issues in HTML documents through ordered AI edit stages and produces measured before/after reports plus PDF/DOCX exports.
- `haccp-drafter` creates a structured HACCP draft from process-step and hazard entries, placing proposals under Hazard Analysis, Critical Control Points, Monitoring Procedures, or Corrective Actions.

Both builds use SuperDocs' async HITL workflow. Proposed changes are displayed and reviewed item by item before commit; `--approve-all` is available only as an explicit machine-automation opt-in.

## SuperDocs Integration

The builds use:

- Base64 document upload.
- Async chat with `approval_mode=ask_every_time`.
- Async job polling and progress states.
- Per-change approve/deny decisions.
- Defensive parsing of JSON-encoded document and approval changes.
- Session job lookup for in-flight work recovery.
- Document detail structure reads for free verification.
- Template upload and template listing.
- Session history and revert helpers.
- PDF, DOCX, HTML, Markdown, and text export paths.

## Reliability and Safety

- Atomic local checkpoints and per-run OS locks.
- Interactive and batch HACCP resume support.
- Deterministic idempotency keys on upload/chat/approval requests.
- Budget floor before billable chat/approval operations.
- Long-request heartbeat and bounded async polling.
- Untrusted source-data boundaries for uploaded HTML and HACCP fields.
- Fail-closed validation for malformed approval changes.
- HACCP disclaimer retention and placement evidence.
- PDF/DOCX package integrity checks without claiming accessibility certification.

## Validation

- `python -m compileall -q common accessible-doc-kit haccp-drafter`
- `python -m pytest -vv`
- Result: 70 tests passed.
- Live smoke test completed successfully with a temporary session: upload, async processing, human approval, completion, and Markdown export.

## Honest Limitations

- Server-side duplicate prevention depends on SuperDocs honoring `Idempotency-Key`; active-job lookup provides an additional documented recovery path.
- HACCP placement evidence is advisory and is not food-safety or regulatory certification.
- PDF/DOCX checks validate readable export containers, not WCAG/PDF-UA conformance.
- Live smoke testing is manual because it requires a secret and consumes an operation.

## Scope


This PR contains the two assigned Task 2 builds. Task 1 is maintained separately in its own private repository.
