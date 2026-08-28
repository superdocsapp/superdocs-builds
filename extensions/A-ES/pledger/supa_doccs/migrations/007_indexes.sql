-- Migration 007: Create all non-primary-key indexes
-- Requirements: 3.3, 6.6, 7.4

BEGIN;

-- Documents indexes
CREATE INDEX IF NOT EXISTS idx_documents_mime_type ON documents(mime_type);
CREATE INDEX IF NOT EXISTS idx_documents_ingested_at ON documents(ingested_at);

-- Document versions indexes
CREATE INDEX IF NOT EXISTS idx_dv_document_id ON document_versions(document_id);
CREATE INDEX IF NOT EXISTS idx_dv_content_hash ON document_versions(content_hash);

-- Runs indexes
CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status);
CREATE INDEX IF NOT EXISTS idx_runs_started_at ON runs(started_at);

-- Run steps indexes
CREATE INDEX IF NOT EXISTS idx_run_steps_run_status_order ON run_steps(run_id, status, step_order DESC);
CREATE INDEX IF NOT EXISTS idx_run_steps_run_id ON run_steps(run_id);
CREATE INDEX IF NOT EXISTS idx_run_steps_status ON run_steps(status);

-- Claims indexes
CREATE INDEX IF NOT EXISTS idx_claims_document_version_id ON claims(document_version_id);
CREATE INDEX IF NOT EXISTS idx_claims_run_id ON claims(run_id);
CREATE INDEX IF NOT EXISTS idx_claims_type ON claims(claim_type);
CREATE INDEX IF NOT EXISTS idx_claims_confidence ON claims(confidence);

-- Source locations indexes
CREATE INDEX IF NOT EXISTS idx_source_locations_claim_id ON source_locations(claim_id);
CREATE INDEX IF NOT EXISTS idx_source_locations_dv_id ON source_locations(document_version_id);

-- Approval queue indexes
CREATE INDEX IF NOT EXISTS idx_aq_claim_id ON approval_queue(claim_id);
CREATE INDEX IF NOT EXISTS idx_aq_status ON approval_queue(status);
CREATE INDEX IF NOT EXISTS idx_aq_status_priority_queued ON approval_queue(status, priority, queued_at);
CREATE INDEX IF NOT EXISTS idx_aq_queued_at ON approval_queue(queued_at);

-- Decisions indexes
CREATE INDEX IF NOT EXISTS idx_decisions_reviewer ON decisions(reviewer_id);

-- Audit events indexes
CREATE INDEX IF NOT EXISTS idx_audit_event_timestamp ON audit_events(event_timestamp);
CREATE INDEX IF NOT EXISTS idx_audit_entity_history ON audit_events(entity_type, entity_id, event_timestamp);
CREATE INDEX IF NOT EXISTS idx_audit_actor ON audit_events(actor_id);

COMMIT;
