# Changelog

## 0.2.0

- Corrected the large-file path to request a presigned URL, PUT the actual bytes without API authorization, and process the uploaded document.
- Added typed sessions, history, saved documents, document detail, archive/restore, and sync/async pagination helpers.
- Added truly streamed sync/async SSE progress and canonical proposed-change-batch double parsing.
- Added automatic and caller-supplied idempotency keys, `Retry-After` support, bounded exponential backoff, and nonblocking async retries.
- Added per-call timeouts, awaiting-human-input job returns, exact-one-source export validation, and specific rich exception classes.
- Added PEP 561 packaging, strict mypy, Ruff, parity tests, credential-leak checks, and versioned sdist/wheel generation.

## 0.1.0

- Initial typed sync/async client prototype.
