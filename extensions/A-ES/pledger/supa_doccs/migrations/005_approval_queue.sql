-- Migration 005: Create approval_queue and decisions tables
-- Requirements: 5.1, 5.2, 5.3, 5.5, 5.7, 7.1, 7.2, 7.3

BEGIN;

-- Create approval_queue table
CREATE TABLE IF NOT EXISTS approval_queue (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    claim_id UUID NOT NULL REFERENCES claims(id) ON DELETE RESTRICT,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    assigned_reviewer VARCHAR(128) NULL,
    queued_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    priority INTEGER NOT NULL DEFAULT 3,
    version INTEGER NOT NULL DEFAULT 1,
    CONSTRAINT chk_approval_queue_status CHECK (
        status IN ('pending', 'approved', 'rejected')
    ),
    CONSTRAINT chk_approval_queue_priority CHECK (priority >= 1 AND priority <= 5)
);

-- Create decisions table
CREATE TABLE IF NOT EXISTS decisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    approval_queue_id UUID NOT NULL REFERENCES approval_queue(id) ON DELETE RESTRICT,
    decision_value VARCHAR(10) NOT NULL,
    reviewer_id VARCHAR(128) NOT NULL,
    decided_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    justification VARCHAR(2000) NOT NULL,
    CONSTRAINT uq_decisions_approval_queue_id UNIQUE (approval_queue_id),
    CONSTRAINT chk_decisions_decision_value CHECK (
        decision_value IN ('approved', 'rejected')
    ),
    CONSTRAINT chk_decisions_justification_length CHECK (length(justification) >= 1)
);

-- Create guard trigger function to prevent decisions on non-pending queue entries
CREATE OR REPLACE FUNCTION guard_decision_on_pending() RETURNS TRIGGER AS $$
DECLARE
  queue_status VARCHAR(20);
BEGIN
  SELECT status INTO queue_status FROM approval_queue WHERE id = NEW.approval_queue_id;
  IF queue_status != 'pending' THEN
    RAISE EXCEPTION 'Cannot record decision: approval_queue entry is %, expected pending', queue_status;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Attach guard trigger to decisions table
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_trigger WHERE tgname = 'trg_guard_decision_on_pending'
  ) THEN
    CREATE TRIGGER trg_guard_decision_on_pending
      BEFORE INSERT ON decisions
      FOR EACH ROW
      EXECUTE FUNCTION guard_decision_on_pending();
  END IF;
END;
$$;

COMMIT;
