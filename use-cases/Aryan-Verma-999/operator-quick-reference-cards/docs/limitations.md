# Current limitations and release boundary

The source-locked verifier remains authoritative. Native PDF text is required
for exact-value evidence; OCR, arbitrary scanned manuals, and unit conversion
are blocked rather than guessed. SuperDocs credentials stay server-side and
live contract tests are opt-in and operation-budgeted.

The public `make run` experience is a fully local, synthetic reviewer path. It
does not pretend to complete the blocked provider review: it verifies the
source-locked card and serves the committed two-page demo PDF only after local
verification and postflight pass.

The live M1 gap is unresolved: after parsing the documented
`document_sync.content` field, the provider returned 6 proposal targets with
no owner among 8 synchronized HTML chunks in read-only recovery, then 31
proposal targets with no owner among 8 chunks in a fresh live run. LineCard
therefore made no provider approval decision and no provider export attempt.
The sanitized reproducible facts are in `docs/superdocs-live-bug-report.md`;
this is intentionally `BLOCKED_REAL_DEFECT`, not a green claim.
