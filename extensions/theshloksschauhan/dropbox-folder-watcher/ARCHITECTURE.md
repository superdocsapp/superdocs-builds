# Architecture: SuperDocs Dropbox Watcher

This document details the architectural decisions and patterns used to implement the SuperDocs Dropbox Folder Watcher, fulfilling the exact specifications in the original design document.

## 1. Core Principles
- **No Lost State**: Every state transition is written to PostgreSQL inside a transaction. If the worker crashes mid-run, it safely resumes.
- **Fail-Safe Preview**: "Preview Mode" is guaranteed to cost $0 via a structural chokepoint. Billable operations are blocked at the lowest SDK-wrapper level, not left to application logic.
- **Dependency Injection**: External API clients (Dropbox and SuperDocs) are abstracted using Python `typing.Protocol`. All tests run against offline fakes.

## 2. Component Pipeline

### The Watcher (Discovery)
- Scans configured Dropbox folders using list_folder.
- Passes every file through a strict filtering pipeline:
  1. Is it our own output? (Anti-loop DB check) -> Ignore
  2. Have we already processed this exact revision? -> Ignore
  3. Is the file stable? (Content-hash debounce) -> Wait
- Creates a `Job` in `DISCOVERED` state, transitions to `QUEUED`.

### The Worker (Execution)
- Atomically claims a `QUEUED` job (prevents double-processing across workers).
- Phase 1: SuperDocs **upload + chat**, then **stops at `REVIEW_PENDING`**.
- A human (or machine via `POST /api/jobs/{id}/approve`) must approve.
- Phase 2: SuperDocs **approve + export**, Dropbox write-back, `known_outputs` registry.

### The API (Visibility & Webhooks)
- FastAPI endpoints providing health metrics, folder configuration management, and full Job audit trails.
- Receives Dropbox webhooks (HMAC-SHA256 verified) to trigger fast-path polling (implemented as hybrid webhook/polling).

## 3. Specific Solutions to Known Pitfalls

### The "Double JSON Parse" Bug
SuperDocs returns proposed changes as a JSON string inside a JSON response. The client explicitly implements a defensive `parse_proposed_changes` function that detects strings and parses a second time, preventing empty diffs.

### Anti-Loop Protection (Layered)
Naming conventions are fragile. This system uses three layers:
1. **Naming Pattern**: Soft check (`.superdocs.` marker in filename).
2. **Path Registry**: Exact output path match in DB.
3. **Hash Registry**: Exact content-hash match in DB.
Only the latter two are authoritative.

### Stability (Half-Written Files)
Dropbox will trigger events before large files are fully uploaded.
- The `StabilityService` maintains a rolling window of observations.
- It requires the `content_hash` to remain unchanged for a configurable `debounce_seconds` window.
- Size checks are ignored in favor of the much safer `content_hash` equality.
