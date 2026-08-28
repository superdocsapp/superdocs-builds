# Implementation Plan: Core PostgreSQL Schema

## Overview

Implement the core PostgreSQL schema for the agentic document-intelligence system as sequential SQL migration files (001–007), followed by SQLAlchemy declarative models, and property-based tests validating the 14 correctness properties. Migrations define tables, triggers, constraints, and indexes. Models provide the ORM layer. Tests use Hypothesis to verify schema invariants against a live Postgres instance.

## Tasks

- [x] 1. Project setup and dependencies
  - [x] 1.1 Add test dependencies to pyproject.toml
    - Add `hypothesis` to the `[dependency-groups] dev` section
    - Verify `pytest`, `sqlalchemy`, and `psycopg2-binary` are already present
    - _Requirements: 8.1_

  - [x] 1.2 Create migration directory structure and runner utility
    - Create `migrations/` directory at project root
    - Create `src/models/` package with `__init__.py`
    - Create `tests/test_schema/` package with `__init__.py`
    - Create a migration runner script `migrations/run_migrations.py` that applies SQL files in order, checking `schema_migrations` to skip already-applied ones
    - _Requirements: 8.1, 8.2, 8.3, 8.5_

- [x] 2. Migration 001: Extensions and schema_migrations table
  - [x] 2.1 Create `migrations/001_extensions_and_migrations.sql`
    - Enable `pgcrypto` extension with `IF NOT EXISTS`
    - Enable `vector` extension with `IF NOT EXISTS`
    - Create `schema_migrations` table (id INTEGER PK, filename VARCHAR(255) NOT NULL, applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW())
    - Wrap in BEGIN/COMMIT transaction
    - Use `IF NOT EXISTS` on all DDL
    - _Requirements: 8.1, 8.2, 8.3, 8.4_

- [x] 3. Migration 002: Documents and document_versions
  - [x] 3.1 Create `migrations/002_documents_and_versions.sql`
    - Create `documents` table with UUID PK (gen_random_uuid()), filename VARCHAR(255) NOT NULL, mime_type VARCHAR(100) NOT NULL with CHECK constraint for allowed types, ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), metadata JSONB NOT NULL DEFAULT '{}'
    - Create `document_versions` table with UUID PK, document_id FK to documents ON DELETE RESTRICT, content_hash CHAR(64) NOT NULL, storage_ref VARCHAR(1024) NOT NULL, version_number INTEGER NOT NULL CHECK >= 1, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    - Add UNIQUE constraint on (document_id, content_hash) and (document_id, version_number)
    - Create `prevent_version_mutation()` trigger function and attach as BEFORE UPDATE trigger on document_versions
    - Wrap in BEGIN/COMMIT with IF NOT EXISTS guards
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 7.1, 7.2, 7.3_

- [x] 4. Migration 003: Runs and run_steps
  - [x] 4.1 Create `migrations/003_runs_and_steps.sql`
    - Create `runs` table with UUID PK, status VARCHAR(20) NOT NULL DEFAULT 'pending' with CHECK for valid statuses, started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), ended_at TIMESTAMPTZ NULL, config_snapshot JSONB NOT NULL DEFAULT '{}', initiator VARCHAR(128) NOT NULL, version INTEGER NOT NULL DEFAULT 1
    - Create `run_steps` table with UUID PK, run_id FK to runs ON DELETE RESTRICT, step_name VARCHAR(128) NOT NULL, step_order INTEGER NOT NULL CHECK >= 1, status VARCHAR(20) NOT NULL DEFAULT 'pending' with CHECK, started_at TIMESTAMPTZ NULL, ended_at TIMESTAMPTZ NULL, input_state JSONB NOT NULL DEFAULT '{}', output_state JSONB NOT NULL DEFAULT '{}', error_details TEXT NULL, retry_count INTEGER NOT NULL DEFAULT 0 CHECK between 0 and 10, version INTEGER NOT NULL DEFAULT 1
    - Add UNIQUE constraint on (run_id, step_order)
    - Create `enforce_run_status_transition()` trigger function implementing the state machine and version auto-increment
    - Attach as BEFORE UPDATE trigger on runs
    - Wrap in BEGIN/COMMIT with IF NOT EXISTS guards
    - _Requirements: 3.1, 3.2, 3.4, 3.5, 4.5, 7.1, 7.2, 7.3_

- [x] 5. Migration 004: Claims and source_locations
  - [x] 5.1 Create `migrations/004_claims_and_sources.sql`
    - Create `claims` table with UUID PK, document_version_id FK to document_versions ON DELETE RESTRICT, run_id FK to runs ON DELETE RESTRICT, extracted_text VARCHAR(10000) NOT NULL, claim_type VARCHAR(128) NOT NULL, confidence NUMERIC(4,3) NOT NULL CHECK between 0.0 and 1.0, extracted_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    - Create `source_locations` table with UUID PK, claim_id FK to claims ON DELETE RESTRICT, document_version_id FK to document_versions ON DELETE RESTRICT, page_number INTEGER NULL CHECK >= 1 when not null, section_id VARCHAR(256) NULL, start_offset INTEGER NOT NULL CHECK >= 0, end_offset INTEGER NOT NULL CHECK >= 0, clause_ref VARCHAR(512) NULL
    - Add CHECK constraint: start_offset < end_offset
    - Wrap in BEGIN/COMMIT with IF NOT EXISTS guards
    - _Requirements: 2.1, 2.2, 2.4, 2.5, 4.2, 7.1, 7.2, 7.3_

- [x] 6. Migration 005: Approval queue and decisions
  - [x] 6.1 Create `migrations/005_approval_queue.sql`
    - Create `approval_queue` table with UUID PK, claim_id FK to claims ON DELETE RESTRICT, status VARCHAR(20) NOT NULL DEFAULT 'pending' with CHECK for pending/approved/rejected, assigned_reviewer VARCHAR(128) NULL, queued_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), priority INTEGER NOT NULL DEFAULT 3 CHECK between 1 and 5, version INTEGER NOT NULL DEFAULT 1
    - Create `decisions` table with UUID PK, approval_queue_id FK to approval_queue ON DELETE RESTRICT with UNIQUE constraint, decision_value VARCHAR(10) NOT NULL CHECK for approved/rejected, reviewer_id VARCHAR(128) NOT NULL, decided_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), justification VARCHAR(2000) NOT NULL CHECK length >= 1
    - Create `guard_decision_on_pending()` trigger function
    - Attach as BEFORE INSERT trigger on decisions
    - Wrap in BEGIN/COMMIT with IF NOT EXISTS guards
    - _Requirements: 5.1, 5.2, 5.3, 5.5, 5.7, 7.1, 7.2, 7.3_

- [x] 7. Migration 006: Audit events
  - [x] 7.1 Create `migrations/006_audit_events.sql`
    - Create `audit_events` table with UUID PK, event_timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(), entity_type VARCHAR(50) NOT NULL with CHECK for valid types, entity_id UUID NOT NULL, action VARCHAR(20) NOT NULL with CHECK for valid actions, actor_id VARCHAR(128) NOT NULL, previous_state JSONB NULL, new_state JSONB NOT NULL, source_ref VARCHAR(128) NULL
    - Create `prevent_audit_mutation()` trigger function that raises exception on UPDATE or DELETE
    - Attach as BEFORE UPDATE OR DELETE trigger on audit_events
    - Wrap in BEGIN/COMMIT with IF NOT EXISTS guards
    - _Requirements: 6.1, 6.2, 6.4, 7.3_

- [x] 8. Migration 007: Indexes
  - [x] 8.1 Create `migrations/007_indexes.sql`
    - Create all non-primary-key indexes using IF NOT EXISTS:
      - `idx_documents_mime_type` on documents(mime_type)
      - `idx_documents_ingested_at` on documents(ingested_at)
      - `idx_dv_document_id` on document_versions(document_id)
      - `idx_dv_content_hash` on document_versions(content_hash)
      - `idx_runs_status` on runs(status)
      - `idx_runs_started_at` on runs(started_at)
      - `idx_run_steps_run_status_order` on run_steps(run_id, status, step_order DESC)
      - `idx_run_steps_run_id` on run_steps(run_id)
      - `idx_run_steps_status` on run_steps(status)
      - `idx_claims_document_version_id` on claims(document_version_id)
      - `idx_claims_run_id` on claims(run_id)
      - `idx_claims_type` on claims(claim_type)
      - `idx_claims_confidence` on claims(confidence)
      - `idx_source_locations_claim_id` on source_locations(claim_id)
      - `idx_source_locations_dv_id` on source_locations(document_version_id)
      - `idx_aq_claim_id` on approval_queue(claim_id)
      - `idx_aq_status` on approval_queue(status)
      - `idx_aq_status_priority_queued` on approval_queue(status, priority, queued_at)
      - `idx_aq_queued_at` on approval_queue(queued_at)
      - `idx_decisions_reviewer` on decisions(reviewer_id)
      - `idx_audit_event_timestamp` on audit_events(event_timestamp)
      - `idx_audit_entity_history` on audit_events(entity_type, entity_id, event_timestamp)
      - `idx_audit_actor` on audit_events(actor_id)
    - Wrap in BEGIN/COMMIT
    - _Requirements: 3.3, 6.6, 7.4_

- [x] 9. Checkpoint - Verify migrations apply cleanly
  - Ensure all migrations apply successfully against a fresh database, ask the user if questions arise.

- [x] 10. SQLAlchemy base and model definitions
  - [x] 10.1 Create `src/models/base.py`
    - Define `Base` class extending `DeclarativeBase`
    - Define `TimestampMixin` with `created_at` mapped column
    - Import common types (uuid, datetime, Decimal)
    - _Requirements: 7.3_

  - [x] 10.2 Create `src/models/documents.py`
    - Define `Document` model mapping to `documents` table
    - Define `DocumentVersion` model mapping to `document_versions` table
    - Include relationship definitions (Document has many DocumentVersions)
    - Map all columns with correct types and constraints
    - _Requirements: 1.1, 1.2_

  - [x] 10.3 Create `src/models/runs.py`
    - Define `Run` model mapping to `runs` table with OCC version column
    - Define `RunStep` model mapping to `run_steps` table with OCC version column
    - Include relationship (Run has many RunSteps)
    - _Requirements: 3.1, 3.2, 4.5_

  - [x] 10.4 Create `src/models/claims.py`
    - Define `Claim` model mapping to `claims` table
    - Define `SourceLocation` model mapping to `source_locations` table
    - Include relationships (Claim has many SourceLocations, linked to DocumentVersion and Run)
    - _Requirements: 2.1, 2.2, 4.2_

  - [x] 10.5 Create `src/models/approval.py`
    - Define `ApprovalQueue` model mapping to `approval_queue` table with OCC version column
    - Define `Decision` model mapping to `decisions` table
    - Include relationships (ApprovalQueue has one Decision, linked to Claim)
    - _Requirements: 5.1, 5.3, 5.5_

  - [x] 10.6 Create `src/models/audit.py`
    - Define `AuditEvent` model mapping to `audit_events` table
    - Map all columns including entity_type, entity_id, action, actor_id, previous_state, new_state, source_ref
    - _Requirements: 6.1_

  - [x] 10.7 Create `src/models/schema_migrations.py`
    - Define `SchemaMigration` model mapping to `schema_migrations` table
    - _Requirements: 8.3_

  - [x] 10.8 Update `src/models/__init__.py` with all model exports
    - Import and re-export all models from the package
    - _Requirements: 7.1_

- [x] 11. Checkpoint - Verify models load without errors
  - Ensure all models import cleanly and match the migration schema, ask the user if questions arise.

- [x] 12. Property-based tests for schema correctness
  - [x] 12.1 Create test fixtures in `tests/test_schema/conftest.py`
    - Set up pytest fixtures for database connection, session, and transaction rollback isolation
    - Create fixtures for pre-populated documents, document_versions, runs, claims for relationship tests
    - Configure Hypothesis settings (min 100 examples)
    - _Requirements: 8.2_

  - [x] 12.2 Create `tests/test_schema/test_documents.py` with property tests for documents and versions
    - **Property 1: MIME Type Validation** — generate random strings and verify only allowed MIME types succeed
    - **Validates: Requirements 1.1, 1.6**
    - **Property 2: Content-Hash Deduplication** — generate pairs of (document_id, content_hash) and verify duplicate pairs raise unique violation
    - **Validates: Requirements 1.3, 7.5**
    - **Property 3: Document Version Immutability** — generate update attempts on content_hash/storage_ref and verify trigger rejection
    - **Validates: Requirements 1.4**
    - **Property 4: Composite Unique Constraints** — generate duplicate (document_id, version_number) pairs and verify rejection
    - **Validates: Requirements 1.5, 3.5**
    - _Requirements: 1.1, 1.3, 1.4, 1.5, 1.6_

  - [x] 12.3 Write property test for source location offset ordering
    - **Property 5: Source Location Offset Ordering**
    - Generate random (start_offset, end_offset) pairs and verify insertion succeeds only when start < end
    - **Validates: Requirements 2.5**

  - [x] 12.4 Write property test for resume query correctness
    - **Property 6: Resume Query Correctness**
    - Generate arbitrary sequences of run_steps with mixed statuses and verify the resume query returns the highest completed step_order
    - **Validates: Requirements 3.3**

  - [x] 12.5 Write property test for run status state machine
    - **Property 7: Run Status State Machine**
    - Generate all pairs of (current_status, new_status) and verify only valid transitions succeed
    - **Validates: Requirements 3.4**

  - [x] 12.6 Write property test for optimistic concurrency control
    - **Property 8: Optimistic Concurrency Control**
    - Generate version values and verify updates with matching version succeed (affecting 1 row) while mismatches affect 0 rows
    - **Validates: Requirements 4.5, 4.6**

  - [x] 12.7 Write property test for one decision per queue entry
    - **Property 9: One Decision Per Queue Entry**
    - Generate scenarios with existing decisions and verify second insert raises unique violation
    - **Validates: Requirements 5.5**

  - [x] 12.8 Write property test for decision guard on pending status
    - **Property 10: Decision Guard on Pending Status**
    - Generate approval_queue entries with non-pending statuses and verify decision insert is rejected by trigger
    - **Validates: Requirements 5.7**

  - [x] 12.9 Write property test for audit events append-only
    - **Property 11: Audit Events Append-Only**
    - Generate existing audit_event rows and verify any UPDATE or DELETE raises trigger exception
    - **Validates: Requirements 6.2**

  - [x] 12.10 Write property test for audit entity history ordering
    - **Property 12: Audit Entity History Ordering**
    - Generate multiple audit_events for the same entity and verify chronological ordering query returns correct sequence
    - **Validates: Requirements 6.4**

  - [x] 12.11 Write property test for ON DELETE RESTRICT enforcement
    - **Property 13: ON DELETE RESTRICT Enforcement**
    - Generate parent-child relationship scenarios and verify deleting a parent with children raises foreign key violation
    - **Validates: Requirements 7.2**

  - [x] 12.12 Write property test for migration idempotency
    - **Property 14: Migration Idempotency**
    - Apply each migration file twice and verify no errors or schema changes on the second application
    - **Validates: Requirements 8.4**

- [x] 13. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties using Hypothesis (min 100 examples per property)
- Migrations are idempotent and transactional — safe to re-run
- Tests use transaction rollback isolation so no cleanup is needed between test runs
- The migration runner checks `schema_migrations` to skip already-applied files (Requirement 8.5)
- OCC version columns are application-enforced via WHERE clauses, not auto-managed by SQLAlchemy

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["2.1"] },
    { "id": 2, "tasks": ["3.1"] },
    { "id": 3, "tasks": ["4.1"] },
    { "id": 4, "tasks": ["5.1"] },
    { "id": 5, "tasks": ["6.1"] },
    { "id": 6, "tasks": ["7.1"] },
    { "id": 7, "tasks": ["8.1"] },
    { "id": 8, "tasks": ["10.1"] },
    { "id": 9, "tasks": ["10.2", "10.3", "10.4", "10.5", "10.6", "10.7"] },
    { "id": 10, "tasks": ["10.8"] },
    { "id": 11, "tasks": ["12.1"] },
    { "id": 12, "tasks": ["12.2", "12.3", "12.4", "12.5", "12.6", "12.7", "12.8", "12.9", "12.10", "12.11", "12.12"] }
  ]
}
```
