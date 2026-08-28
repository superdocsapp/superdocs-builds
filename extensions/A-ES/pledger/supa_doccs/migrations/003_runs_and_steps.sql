-- Migration 003: Create runs and run_steps tables
-- Requirements: 3.1, 3.2, 3.4, 3.5, 4.5, 7.1, 7.2, 7.3

BEGIN;

-- Create runs table
CREATE TABLE IF NOT EXISTS runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at TIMESTAMPTZ NULL,
    config_snapshot JSONB NOT NULL DEFAULT '{}',
    initiator VARCHAR(128) NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    CONSTRAINT chk_runs_status CHECK (
        status IN ('pending', 'running', 'completed', 'failed', 'cancelled')
    )
);

-- Create run_steps table
CREATE TABLE IF NOT EXISTS run_steps (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL REFERENCES runs(id) ON DELETE RESTRICT,
    step_name VARCHAR(128) NOT NULL,
    step_order INTEGER NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    started_at TIMESTAMPTZ NULL,
    ended_at TIMESTAMPTZ NULL,
    input_state JSONB NOT NULL DEFAULT '{}',
    output_state JSONB NOT NULL DEFAULT '{}',
    error_details TEXT NULL,
    retry_count INTEGER NOT NULL DEFAULT 0,
    version INTEGER NOT NULL DEFAULT 1,
    CONSTRAINT chk_run_steps_step_order CHECK (step_order >= 1),
    CONSTRAINT chk_run_steps_status CHECK (
        status IN ('pending', 'running', 'completed', 'failed', 'skipped')
    ),
    CONSTRAINT chk_run_steps_retry_count CHECK (retry_count >= 0 AND retry_count <= 10),
    CONSTRAINT uq_run_steps_run_id_step_order UNIQUE (run_id, step_order)
);

-- Create state machine trigger function for run status transitions
CREATE OR REPLACE FUNCTION enforce_run_status_transition() RETURNS TRIGGER AS $$
DECLARE
  valid_transitions JSONB := '{
    "pending": ["running"],
    "running": ["completed", "failed", "cancelled"]
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

-- Attach state machine trigger to runs
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_trigger WHERE tgname = 'trg_enforce_run_status_transition'
  ) THEN
    CREATE TRIGGER trg_enforce_run_status_transition
      BEFORE UPDATE ON runs
      FOR EACH ROW
      EXECUTE FUNCTION enforce_run_status_transition();
  END IF;
END;
$$;

COMMIT;
