-- Migration 002: Create documents and document_versions tables
-- Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 7.1, 7.2, 7.3

BEGIN;

-- Create documents table
CREATE TABLE IF NOT EXISTS documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    filename VARCHAR(255) NOT NULL,
    mime_type VARCHAR(100) NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata JSONB NOT NULL DEFAULT '{}',
    CONSTRAINT chk_documents_mime_type CHECK (
        mime_type IN (
            'application/pdf',
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            'text/plain'
        )
    )
);

-- Create document_versions table
CREATE TABLE IF NOT EXISTS document_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE RESTRICT,
    content_hash CHAR(64) NOT NULL,
    storage_ref VARCHAR(1024) NOT NULL,
    version_number INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_dv_version_number CHECK (version_number >= 1),
    CONSTRAINT uq_dv_document_content_hash UNIQUE (document_id, content_hash),
    CONSTRAINT uq_dv_document_version_number UNIQUE (document_id, version_number)
);

-- Create immutability trigger function for document_versions
CREATE OR REPLACE FUNCTION prevent_version_mutation() RETURNS TRIGGER AS $$
BEGIN
  IF OLD.content_hash IS DISTINCT FROM NEW.content_hash THEN
    RAISE EXCEPTION 'content_hash is immutable';
  END IF;
  IF OLD.storage_ref IS DISTINCT FROM NEW.storage_ref THEN
    RAISE EXCEPTION 'storage_ref is immutable';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Attach immutability trigger to document_versions
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_trigger WHERE tgname = 'trg_prevent_version_mutation'
  ) THEN
    CREATE TRIGGER trg_prevent_version_mutation
      BEFORE UPDATE ON document_versions
      FOR EACH ROW
      EXECUTE FUNCTION prevent_version_mutation();
  END IF;
END;
$$;

COMMIT;
