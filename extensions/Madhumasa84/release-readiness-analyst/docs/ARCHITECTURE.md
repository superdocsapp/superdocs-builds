# Architecture

## Boundaries

React calls FastAPI. FastAPI validates authenticated, workspace-scoped requests and delegates to the workflow service. Workers execute durable stages and write checkpoints, provenance events, report revisions, and stage metrics. PostgreSQL is the production system of record; pgvector supports semantic retrieval. Object storage is the production location for source/report artifacts. Offline tests use SQLite and deterministic hash embeddings.

## Durable workflow

`parse_sources -> extract_requirements -> map_evidence -> analyze_contradictions -> evaluate_release_rules -> draft_report`

Each stage commits its output before the next stage begins. `completed_stages` is persisted in the run state. A worker termination leaves the run resumable; resume skips committed stages and reruns only the interrupted stage. New sources clear downstream checkpoints while retaining immutable existing chunks.

## Data model

The ORM defines workspaces, runs, sources, source chunks, findings, decisions, report revisions, stage metrics, and provenance events. Source hashes and version fields prevent silent replacement. Production applies `CREATE EXTENSION vector` and an HNSW cosine index; the SQLite test schema keeps embeddings as JSON so tests remain credential-free and portable.

## Evidence and report revisions

Findings reference immutable source IDs, SHA-256 hashes, filenames, line ranges, quotes, and verification status. Report revisions are append-only. A revision records `changed_finding_ids`, allowing the UI to show incremental updates and proving unaffected finding IDs were reused.

## Approval and machine operations

The decision endpoint rejects unknown and duplicate IDs. A run cannot complete while required findings lack decisions. The `/mcp` endpoint exposes the same typed read, resume, report, and decision operations used by machine clients; a production MCP transport can wrap this contract without granting arbitrary tools.

## Isolation

Workspace and run IDs are required on persisted records. A per-run lease and process-local lock prevent duplicate in-process execution; production deployment should add a PostgreSQL advisory lock or equivalent lease service. Optimistic state versions and unique decision constraints prevent lost updates.
