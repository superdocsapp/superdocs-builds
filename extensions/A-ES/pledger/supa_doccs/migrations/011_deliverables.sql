-- Migration 011: Persisted pipeline deliverables
--
-- The finalize node assembles the run's deliverable (sections of claims,
-- each with content hashes and citations). Previously this existed only
-- in-process (ServiceRegistry.deliverable), populated exclusively by the
-- incremental flow — a plain first run had no retrievable deliverable.
--
-- One row per finalized run. Sections JSONB stores the serialized
-- sections including per-claim citations (source_document_id,
-- citation_status, span fields).

BEGIN;

CREATE TABLE IF NOT EXISTS deliverables (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL UNIQUE REFERENCES runs(id) ON DELETE CASCADE,
    deliverable_hash VARCHAR(64) NOT NULL,
    section_count INTEGER NOT NULL DEFAULT 0,
    claim_count INTEGER NOT NULL DEFAULT 0,
    sections JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_deliverables_run_id ON deliverables (run_id);

COMMIT;
