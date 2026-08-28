-- Migration 013: 'completed_with_persistence_gap' run status
--
-- Durability writes (claims/source_locations at extract_claims,
-- audit_events for history) are best-effort: when they fail after one
-- retry, the run must NOT report a plain 'completed'. The new status
-- makes the persistence gap visible at the run-list level.

BEGIN;

-- 'completed_with_persistence_gap' is 31 chars; the column was VARCHAR(20).
ALTER TABLE runs ALTER COLUMN status TYPE VARCHAR(40);

ALTER TABLE runs DROP CONSTRAINT chk_runs_status;
ALTER TABLE runs ADD CONSTRAINT chk_runs_status CHECK (
    status IN (
        'pending', 'running', 'completed', 'failed', 'cancelled',
        'completed_with_persistence_gap'
    )
);

-- Extend the state machine: a running run may land in the gap status.
CREATE OR REPLACE FUNCTION enforce_run_status_transition() RETURNS TRIGGER AS $$
DECLARE
  valid_transitions JSONB := '{
    "pending": ["running"],
    "running": ["completed", "failed", "cancelled", "completed_with_persistence_gap"]
  }'::jsonb;
  allowed_next JSONB;
BEGIN
  IF OLD.status = NEW.status THEN RETURN NEW; END IF;
  allowed_next := valid_transitions -> OLD.status;
  IF allowed_next IS NULL OR NOT (allowed_next ? NEW.status) THEN
    RAISE EXCEPTION 'Invalid run status transition: % → %', OLD.status, NEW.status;
  END IF;
  NEW.version := OLD.version + 1;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMIT;
