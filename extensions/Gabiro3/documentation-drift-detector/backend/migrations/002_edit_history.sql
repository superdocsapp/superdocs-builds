-- 002_edit_history.sql: make an approved fix reach the document, and keep
-- a readable record of every edit that landed.
--
-- Two gaps this closes:
--   1. Approving a finding wrote a review_decisions row and nothing else. The
--      apply state now lives on the finding itself, so an approval that never
--      reached the document is visible instead of silent.
--   2. applied_edits stored only SuperDocs ids — enough to prove an edit
--      happened, useless for showing what it did. It now carries the chunk and
--      its before/after content, which is what a document's history is made of.
--
-- Written to be idempotent: 001_init.sql is mounted into
-- docker-entrypoint-initdb.d, which only runs when the volume is first
-- created, so this file has to be safe to re-run against a live database.

-- Apply state of a finding, distinct from the human's review decision.
-- approved = "a human said yes"; apply_status = "what happened next".
ALTER TABLE findings ADD COLUMN IF NOT EXISTS apply_status TEXT;
ALTER TABLE findings ADD COLUMN IF NOT EXISTS apply_reason TEXT;
ALTER TABLE findings ADD COLUMN IF NOT EXISTS applied_at TIMESTAMPTZ;

-- The edit history itself. document_id is denormalised from the finding so
-- history survives as a document-scoped record and can be read with one
-- index hit rather than a join through findings.
ALTER TABLE applied_edits ADD COLUMN IF NOT EXISTS document_id UUID REFERENCES documents(id);
ALTER TABLE applied_edits ADD COLUMN IF NOT EXISTS chunk_id TEXT;
ALTER TABLE applied_edits ADD COLUMN IF NOT EXISTS before_html TEXT;
ALTER TABLE applied_edits ADD COLUMN IF NOT EXISTS after_html TEXT;
ALTER TABLE applied_edits ADD COLUMN IF NOT EXISTS before_hash TEXT;
ALTER TABLE applied_edits ADD COLUMN IF NOT EXISTS after_hash TEXT;
ALTER TABLE applied_edits ADD COLUMN IF NOT EXISTS proposed_old TEXT;
ALTER TABLE applied_edits ADD COLUMN IF NOT EXISTS proposed_new TEXT;

-- Idempotency was enforced only by a SELECT-then-INSERT in Python, which two
-- concurrent applies can both pass. The database is the only place that can
-- actually hold this invariant.
CREATE UNIQUE INDEX IF NOT EXISTS idx_applied_edits_finding
    ON applied_edits (finding_id);

-- History is always read as "this document, newest first".
CREATE INDEX IF NOT EXISTS idx_applied_edits_document
    ON applied_edits (document_id, applied_at DESC);

-- Backfill document_id for edits recorded before this migration so their
-- history is not orphaned.
UPDATE applied_edits ae
   SET document_id = f.document_id
  FROM findings f
 WHERE f.id = ae.finding_id
   AND ae.document_id IS NULL;
