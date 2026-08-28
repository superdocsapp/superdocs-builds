-- Migration 010: Extend approval_queue to back ApprovalService contract
--
-- The Phase 2.3 schema modeled queue entries as claim-scoped rows only
-- (claim_id NOT NULL). The ApprovalService / approval API operate on
-- items that carry run_id, item_type, and an arbitrary JSONB payload,
-- and may exist independently of any claims row. This migration adds
-- those columns so approval_queue can durably back the service layer.
--
-- The decisions table is unchanged — it already stores reviewer_id,
-- decision_value, justification, decided_at with a unique constraint
-- per queue entry.

BEGIN;

-- Items may be enqueued without a backing claim (e.g. conflicts,
-- proposed updates), so claim_id becomes optional.
ALTER TABLE approval_queue ALTER COLUMN claim_id DROP NOT NULL;

ALTER TABLE approval_queue
    ADD COLUMN IF NOT EXISTS run_id UUID NULL,
    ADD COLUMN IF NOT EXISTS item_type VARCHAR(32) NOT NULL DEFAULT 'finding',
    ADD COLUMN IF NOT EXISTS payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS decided_at TIMESTAMPTZ NULL;

CREATE INDEX IF NOT EXISTS idx_approval_queue_run_id_status
    ON approval_queue (run_id, status);

COMMIT;
