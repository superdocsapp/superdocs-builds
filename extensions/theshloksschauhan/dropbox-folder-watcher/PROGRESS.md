# Assumptions & Progress

## Assumptions
- Assigned S2 Dropbox folder watcher with write-back (Task 2.1). Task 1 lives in the private `doctask-*` repo.
- PostgreSQL for durable job state; SQLite in-memory for keyless tests.
- Polling is the source of truth; webhooks trigger an opportunistic scan.
- Client isolation is folder-root path scoping, not Dropbox OAuth ACLs.

## Progress
- Human gate: worker stops at `REVIEW_PENDING`; export/write-back only after approve.
- Preview toggle is process-wide and blocks billable SuperDocs calls.
- Operation budget enforced before new jobs are created.
- Webhook POST attempts a folder scan (falls back to daemon poll).
- Folder nomination rejected if the path is outside the client root.
- Dead Vite sidebar removed; treatments are the three assigned modes.
- Task 4 draft: `SUBMISSION.md`.
