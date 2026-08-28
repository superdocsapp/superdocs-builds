-- Migration 009: Create piles and pile_documents tables, add pile_id to runs
-- Invariants: 9, 10, 11, 12

BEGIN;

-- Create piles table
CREATE TABLE IF NOT EXISTS piles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata JSONB NOT NULL DEFAULT '{}',
    CONSTRAINT chk_piles_status CHECK (
        status IN ('active', 'archived')
    )
);

-- Junction table: which documents belong to which pile
CREATE TABLE IF NOT EXISTS pile_documents (
    pile_id UUID NOT NULL REFERENCES piles(id) ON DELETE RESTRICT,
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE RESTRICT,
    added_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (pile_id, document_id)
);

-- Index for fast lookup of all piles a document belongs to
CREATE INDEX IF NOT EXISTS idx_pile_documents_document_id
    ON pile_documents(document_id);

-- Add pile_id to runs (nullable for backward compatibility with old one-shot runs)
ALTER TABLE runs
    ADD COLUMN IF NOT EXISTS pile_id UUID NULL REFERENCES piles(id) ON DELETE RESTRICT;

-- Index for fast lookup of all runs against a pile
CREATE INDEX IF NOT EXISTS idx_runs_pile_id
    ON runs(pile_id) WHERE pile_id IS NOT NULL;

-- Trigger to keep piles.updated_at current
CREATE OR REPLACE FUNCTION update_pile_timestamp() RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at := NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_trigger WHERE tgname = 'trg_update_pile_timestamp'
  ) THEN
    CREATE TRIGGER trg_update_pile_timestamp
      BEFORE UPDATE ON piles
      FOR EACH ROW
      EXECUTE FUNCTION update_pile_timestamp();
  END IF;
END;
$$;

COMMIT;
