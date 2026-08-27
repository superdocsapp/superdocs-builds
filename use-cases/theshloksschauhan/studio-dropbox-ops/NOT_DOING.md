# Deliberate cuts for the S2 Dropbox folder watcher (Task 2.1)

## Cut: Multi-tenant auth and Dropbox OAuth per client
**Why:** S2 band; a shared admin token and single Dropbox app token is enough to prove the loop. Full OAuth per client folder would dominate the build.
**Impact:** Client isolation is enforced by folder path scoping in config, not by Dropbox shared-link permissions.

## Cut: Item-level approve/reject of individual proposed changes
**Why:** SuperDocs approve is document-level in the four-call contract. Partial approval would need custom diff splitting.
**Impact:** Human gate is job-level: approve all proposed changes or reject the job.

## Cut: Real-time webhook-driven scan
**Why:** Polling + debounce already handles half-written files; webhook endpoint verifies signatures but fast-path scan deferred.
**Impact:** Slightly higher latency on detection; no correctness loss.

## Cut: MCP server for Task 2
**Why:** REST API exposes approve/reject/list for machine driving; MCP reserved for Task 1 private repo.
**Impact:** Behavior #4 for the watcher is via REST, not MCP.

## Cut: PostgreSQL-only tests for Task 2
**Why:** SQLite in-memory keeps `pytest` fast and keyless; production uses PostgreSQL via Docker.
**Impact:** UUID/pg-specific edge cases tested in integration manually.
