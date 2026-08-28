-- Migration 006: Create audit_events table with append-only enforcement
-- Requirements: 6.1, 6.2, 6.4, 7.3

BEGIN;

-- Create audit_events table
CREATE TABLE IF NOT EXISTS audit_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    entity_type VARCHAR(50) NOT NULL,
    entity_id UUID NOT NULL,
    action VARCHAR(20) NOT NULL,
    actor_id VARCHAR(128) NOT NULL,
    previous_state JSONB NULL,
    new_state JSONB NOT NULL,
    source_ref VARCHAR(128) NULL,
    CONSTRAINT chk_audit_events_entity_type CHECK (
        entity_type IN ('document', 'document_version', 'claim', 'source_location', 'run', 'run_step', 'approval_queue', 'decision')
    ),
    CONSTRAINT chk_audit_events_action CHECK (
        action IN ('created', 'updated', 'status_changed', 'deleted')
    )
);

-- Create trigger function that prevents any UPDATE or DELETE on audit_events
CREATE OR REPLACE FUNCTION prevent_audit_mutation() RETURNS TRIGGER AS $$
BEGIN
  RAISE EXCEPTION 'audit_events is append-only: % operations are forbidden', TG_OP;
END;
$$ LANGUAGE plpgsql;

-- Attach as BEFORE UPDATE OR DELETE trigger on audit_events
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_trigger WHERE tgname = 'trg_prevent_audit_mutation'
  ) THEN
    CREATE TRIGGER trg_prevent_audit_mutation
      BEFORE UPDATE OR DELETE ON audit_events
      FOR EACH ROW
      EXECUTE FUNCTION prevent_audit_mutation();
  END IF;
END;
$$;

COMMIT;
