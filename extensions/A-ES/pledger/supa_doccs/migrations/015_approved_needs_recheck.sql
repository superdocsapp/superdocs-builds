-- Migration 015: 'approved_needs_recheck' queue status + one-off flag pass.
--
-- Audit gap (run eef332ea, item 4a705e77...): findings were approved with
-- zero citations — or only citations whose source_location is null — before
-- the frontend unverifiable-marker fix existed. Such approvals silently
-- looked like normal, evidence-backed approvals.
--
-- This migration:
--   1. Widens approval_queue.status (22-char value exceeds VARCHAR(20))
--      and extends the status check constraint.
--   2. One-off data pass: every item already in 'approved' whose payload
--      has no source_citations array, an empty one, or no citation with a
--      grounded + non-null source_location is re-flagged as
--      'approved_needs_recheck'. Decisions rows are left intact so the
--      original approval record remains auditable.

BEGIN;

ALTER TABLE approval_queue ALTER COLUMN status TYPE VARCHAR(40);

ALTER TABLE approval_queue DROP CONSTRAINT chk_approval_queue_status;
ALTER TABLE approval_queue ADD CONSTRAINT chk_approval_queue_status CHECK (
    status IN ('pending', 'approved', 'rejected', 'approved_needs_recheck')
);

UPDATE approval_queue q
SET status = 'approved_needs_recheck'
WHERE q.status = 'approved'
  AND (
        jsonb_array_length(COALESCE(q.payload->'source_citations', '[]'::jsonb)) = 0
        OR NOT EXISTS (
            SELECT 1
            FROM jsonb_array_elements(
                COALESCE(q.payload->'source_citations', '[]'::jsonb)
            ) c
            WHERE (c->>'citation_status') = 'grounded'
              AND jsonb_typeof(c->'source_location') = 'object'
          )
      );

COMMIT;
