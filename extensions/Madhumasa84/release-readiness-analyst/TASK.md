# Task plan

## Mandatory implementation scope

- [x] FastAPI backend and typed service boundaries
- [x] Durable staged workflow with persisted checkpoints
- [x] PostgreSQL/pgvector production migration path and SQLite offline fixtures
- [x] React interface with progress, citations, findings, decisions, and report revisions
- [x] Document ingestion, hashing, source provenance, and line citations
- [x] Grounded deterministic findings for coverage, contradictions, missing evidence, and prompt-injection content
- [x] Kill-and-resume recovery and same-run locking
- [x] Explicit item-level approval/rejection/request-more-evidence
- [x] Incremental source updates with changed-finding tracking
- [x] Concurrent-run isolation tests
- [x] MCP-compatible machine operations
- [x] Stage duration, token, and estimated-cost metrics
- [x] Offline deterministic fixtures and failure-injection tests

## Before submission

- [ ] Reconcile every literal clause in the assigned task PDF.
- [ ] Confirm private repository/access requirements.
- [ ] Configure production authentication, object storage, and secret management.
- [ ] Run the clean three-minute demo from a fresh checkout.
