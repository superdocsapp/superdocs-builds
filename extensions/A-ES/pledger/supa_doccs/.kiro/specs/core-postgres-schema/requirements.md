# Requirements Document

## Introduction

This feature defines the core PostgreSQL schema for the agentic document-intelligence system. The schema must support the complete lifecycle of document processing: ingesting source documents, extracting claims/facts with precise source attribution, routing claims through a human-approval queue, tracking run/session state for resumability, and maintaining a full audit trail of every state change. The database runs on pgvector/pgvector:pg16 (PostgreSQL 16 with the vector extension) inside the existing Docker Compose stack, accessed via SQLAlchemy from the FastAPI service.

## Glossary

- **Schema**: The set of PostgreSQL tables, columns, indexes, constraints, and relationships that constitute the persistent data layer.
- **Document**: A source file (PDF, DOCX, or plain text) ingested into the system for analysis.
- **Document_Version**: An immutable snapshot of a Document at a specific point in time, identified by a content hash.
- **Claim**: A discrete factual assertion extracted from a Document_Version by an agent, such as "APR is 24%" or "Processing fee is 500 PHP."
- **Source_Location**: The precise position within a Document_Version from which a Claim was extracted, specified by page/section and character span or clause reference.
- **Run**: A single end-to-end execution of the document-processing pipeline, orchestrated by LangGraph, consisting of ordered Steps.
- **Step**: An individually checkpointed unit of work within a Run, representing one discrete operation (e.g., ingest, extract, classify, review).
- **Approval_Queue**: The set of Claims awaiting human review (approve or reject) before promotion to the verified-claims state.
- **Decision**: A recorded human judgment (approve or reject) on a specific Claim, including who decided and when.
- **Audit_Event**: An immutable, append-only record of a state change to any tracked entity, capturing what changed, when, by whom, and the causal source.
- **Concurrent_Runs**: Two or more Runs executing simultaneously that may reference or modify overlapping Documents.

---

## Requirements

### Requirement 1: Document and Version Storage

**User Story:** As a compliance analyst, I want every ingested document stored with full version history, so that I can always trace which version of a document produced a given claim.

#### Acceptance Criteria

1. THE Schema SHALL include a `documents` table with columns for a unique identifier, original filename (maximum 255 characters), MIME type, ingestion timestamp, and metadata (JSONB). THE Schema SHALL enforce a CHECK constraint on MIME type restricting values to 'application/pdf', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', and 'text/plain'.
2. THE Schema SHALL include a `document_versions` table with columns for a unique identifier, a foreign key to `documents`, a content hash (SHA-256, stored as a 64-character hex string), a storage reference (URI or path to the stored content, maximum 1024 characters), version number (integer starting at 1 and incrementing sequentially per document), and creation timestamp.
3. WHEN a Document is ingested with content identical to an existing Document_Version (same content hash), THE Schema SHALL enforce a UNIQUE constraint on the content hash column that prevents inserting a duplicate row, allowing the system to reference the existing Document_Version instead.
4. THE Schema SHALL enforce that each Document_Version is immutable — no UPDATE or DELETE operations are permitted on content hash or storage reference columns after insertion.
5. THE Schema SHALL enforce that the version number for each Document_Version is unique per document via a UNIQUE constraint on (document_id, version_number), and that version numbers are positive integers (CHECK constraint: version_number >= 1).
6. IF a document is ingested with a MIME type not in the allowed set, THEN THE Schema SHALL reject the insertion with a constraint violation.

---

### Requirement 2: Claim Extraction with Source Attribution

**User Story:** As an auditor, I want every extracted claim linked to the exact location in the source document, so that I can verify any claim by navigating directly to its origin.

#### Acceptance Criteria

1. THE Schema SHALL include a `claims` table with columns for a unique identifier, a foreign key to `document_versions`, extracted text (maximum 10,000 characters), claim type/category, confidence score (numeric between 0.0 and 1.0 inclusive, enforced via CHECK constraint), extraction timestamp, and the Run identifier that produced the Claim.
2. THE Schema SHALL include a `source_locations` table with columns for a unique identifier, a foreign key to `claims`, a foreign key to `document_versions`, page number (nullable for unstructured text, CHECK constraint page_number >= 1 when not null), section identifier (nullable), start character offset (non-negative integer), end character offset (non-negative integer), and clause reference (nullable).
3. WHEN a Claim is inserted, THE Schema SHALL require at least one corresponding Source_Location row linking the Claim to a position in a Document_Version.
4. THE Schema SHALL support a single Claim being attributed to multiple Source_Locations (e.g., a claim derived from cross-referencing two clauses).
5. THE `source_locations` table SHALL enforce that start character offset is less than end character offset via a CHECK constraint.

---

### Requirement 3: Run and Step Tracking for Resumability

**User Story:** As a system operator, I want each pipeline run tracked at the step level with persistent state, so that a killed or failed run can resume from the last completed step without reprocessing.

#### Acceptance Criteria

1. THE Schema SHALL include a `runs` table with columns for a unique identifier, status (pending, running, completed, failed, cancelled), start timestamp, end timestamp (nullable), configuration snapshot (JSONB), and initiator identifier.
2. THE Schema SHALL include a `run_steps` table with columns for a unique identifier, a foreign key to `runs`, step name (maximum 128 characters), step order (integer, CHECK constraint enforcing step_order >= 1), status (pending, running, completed, failed, skipped), start timestamp, end timestamp (nullable), input state reference (JSONB), output state reference (JSONB), error details (nullable text), and a retry count (integer, default 0, CHECK constraint enforcing retry_count between 0 and 10 inclusive).
3. WHEN a Run is resumed after interruption, THE Schema SHALL support identifying the last completed Step for that Run via an index on (run_id, status, step_order) that enables ordering by step_order descending and filtering by status = 'completed'.
4. THE Schema SHALL enforce that a Run's status transitions follow the valid state machine: pending → running → (completed | failed | cancelled), with no backward transitions, enforced via a CHECK constraint or trigger that prevents status from moving to a prior state in the sequence.
5. THE `run_steps` table SHALL enforce a unique constraint on (run_id, step_order) to prevent duplicate step entries within a single Run.
6. WHILE a Step has status `running`, THE Schema SHALL record the start timestamp and leave end timestamp NULL until the Step reaches a terminal status (completed, failed, or skipped).
7. IF a Run is resumed and a Step has status `running` from a prior interrupted execution, THEN THE Schema SHALL allow that Step's status to be updated to `failed` with error details indicating interruption, so that the Run can proceed from the next Step.

---

### Requirement 4: Concurrent Run Isolation

**User Story:** As a system operator, I want the schema to support concurrent runs touching the same documents without data corruption, so that parallel processing is safe and predictable.

#### Acceptance Criteria

1. THE Schema SHALL use advisory locks or row-level locking strategies that allow two Runs to read the same Document_Version concurrently without blocking.
2. THE Schema SHALL associate every Claim with the specific Run that produced it via a NOT NULL foreign key (`run_id`) on the `claims` table, ensuring that Claims from one Run are never attributed to another Run.
3. THE Schema SHALL isolate Run state (the `runs` and `run_steps` tables) such that a failure in one Run does not alter the step records of another Run — each Run's rows are scoped exclusively by its own `run_id` primary key.
4. WHEN two concurrent Runs extract Claims from the same Document_Version, THE Schema SHALL store both sets of Claims independently, each linked to its originating Run.
5. THE Schema SHALL include an integer `version` column (default 1) on the `runs`, `run_steps`, and `approval_queue` tables to support optimistic concurrency control; any UPDATE to these rows SHALL increment the version and include a WHERE clause matching the expected prior version.
6. IF an optimistic concurrency update fails (zero rows affected because the version did not match), THEN the application layer SHALL treat this as a conflict requiring retry or error reporting.

---

### Requirement 5: Pending-Approval Queue

**User Story:** As a compliance reviewer, I want a queue of claims awaiting my decision, so that I can approve or reject each one with a recorded justification.

#### Acceptance Criteria

1. THE Schema SHALL include an `approval_queue` table with columns for a unique identifier, a foreign key to `claims`, a status (pending, approved, rejected), assigned reviewer (nullable), queued timestamp, and priority level (integer from 1 to 5, where 1 is highest priority).
2. WHEN a Claim is promoted to the Approval_Queue, THE Schema SHALL set the queue entry status to `pending` and record the queued timestamp.
3. THE Schema SHALL include a `decisions` table with columns for a unique identifier, a foreign key to `approval_queue`, decision value (approved or rejected), reviewer identifier, decision timestamp, and justification text (minimum 1 character, maximum 2000 characters, enforced via CHECK constraint).
4. WHEN a Decision is recorded, THE Schema SHALL update the corresponding `approval_queue` entry status to match the decision value (approved or rejected).
5. THE Schema SHALL enforce that each `approval_queue` entry receives at most one final Decision (unique constraint on approval_queue foreign key in `decisions`).
6. IF a Claim is re-queued after rejection (e.g., after re-extraction), THEN THE Schema SHALL create a new `approval_queue` entry rather than modifying the existing one, preserving the historical decision.
7. IF a Decision insert is attempted against an `approval_queue` entry whose status is not `pending`, THEN THE Schema SHALL reject the insert via a CHECK or trigger constraint, ensuring decisions are only recorded on pending entries.

---

### Requirement 6: Audit Trail

**User Story:** As a compliance officer, I want a complete, immutable audit trail that records every state change across the system, so that I can answer "what changed, when, and because of which source" at any historical point.

#### Acceptance Criteria

1. THE Schema SHALL include an `audit_events` table with columns for a unique identifier, event timestamp, entity type (one of: document, document_version, claim, source_location, run, run_step, approval_queue, decision), entity identifier, action (created, updated, status_changed, deleted), actor identifier (user or system/run), previous state (JSONB, nullable for `created` actions), new state (JSONB), and source reference (nullable — the Run, Decision, or Document_Version that caused the change).
2. THE `audit_events` table SHALL be append-only — no UPDATE or DELETE operations are permitted on audit rows.
3. WHEN any tracked entity (document, document_version, claim, source_location, run, run_step, approval_queue, or decision) changes state through creation, status transition, or field update, THE Schema SHALL require an Audit_Event row to be inserted within the same database transaction as the triggering change.
4. THE Schema SHALL support querying the full state history of any entity by filtering `audit_events` on entity type and entity identifier, ordered by event timestamp.
5. IF a state change is initiated by a Run or a Document_Version ingestion, THEN THE Schema SHALL record the originating Run identifier or Document_Version identifier in the source reference column; IF a state change is initiated by a human Decision, THEN THE Schema SHALL record the Decision identifier in the source reference column; IF no causal source is identifiable (e.g., administrative corrections), THEN THE Schema SHALL permit the source reference to remain NULL.
6. THE Schema SHALL define an index on `audit_events` covering the event timestamp column to support time-range queries, and a composite index on (entity_type, entity_id, event_timestamp) to support entity-history queries.
7. IF the Audit_Event insertion fails within a transaction, THEN THE Schema SHALL cause the entire transaction (including the triggering state change) to roll back, ensuring no state change can occur without a corresponding audit record.

---

### Requirement 7: Referential Integrity and Constraints

**User Story:** As a developer, I want the schema to enforce referential integrity at the database level, so that orphaned or inconsistent records are structurally impossible.

#### Acceptance Criteria

1. THE Schema SHALL define foreign key constraints between `document_versions` and `documents`, between `claims` and `document_versions`, between `claims` and `runs`, between `source_locations` and `claims`, between `source_locations` and `document_versions`, between `approval_queue` and `claims`, between `decisions` and `approval_queue`, and between `run_steps` and `runs`, with all foreign key columns defined as NOT NULL.
2. THE Schema SHALL use ON DELETE RESTRICT for all foreign keys referencing `documents`, `document_versions`, `claims`, `runs`, and `approval_queue` to prevent deletion of any parent record that is still referenced by child rows.
3. THE Schema SHALL use UUID as the primary key type for all tables to support distributed ID generation without coordination.
4. THE Schema SHALL define indexes on all foreign key columns and on the following filter columns: status columns in `runs`, `run_steps`, `approval_queue`, and `claims`; `event_timestamp` and `entity_type` columns in `audit_events`; and `queued_timestamp` in `approval_queue`.
5. THE Schema SHALL define a UNIQUE constraint on the `content_hash` column of `document_versions` within the scope of a single `document_id` to prevent duplicate version rows for the same document content.

---

### Requirement 8: Schema Migration Support

**User Story:** As a developer, I want the schema to be defined as versioned migration scripts, so that any environment (local, CI, production) can reproducibly reach the current schema state.

#### Acceptance Criteria

1. THE Schema SHALL be expressed as one or more SQL migration files, each prefixed with a sequential integer identifier (e.g., 001, 002, 003), that can be applied in ascending order from an empty database to reach the current schema state.
2. WHEN a migration file is applied, THE Schema SHALL execute it within a single database transaction so that it either fully succeeds or fully rolls back, leaving no partial schema changes.
3. THE Schema SHALL include a `schema_migrations` table that records which migrations have been applied, storing at minimum the migration identifier, the filename, and the timestamp of application.
4. THE migration files SHALL use `IF NOT EXISTS` guards on all CREATE TABLE, CREATE INDEX, and CREATE EXTENSION statements to remain idempotent for object-creation operations.
5. IF a migration is requested whose sequential identifier is lower than or equal to the highest already-applied migration recorded in `schema_migrations`, THEN THE Schema SHALL skip that migration without re-applying it.
