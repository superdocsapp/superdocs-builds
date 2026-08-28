-- Migration 014: Document fact view support
--
-- The document detail view shows, per extracted fact: field name,
-- extraction method (structured/llm), value, and citation. claims only
-- stored claim_type/extracted_text; the field name was buried in
-- claim_type formatting and the extraction path was not recorded at all.

BEGIN;

ALTER TABLE claims
    ADD COLUMN IF NOT EXISTS field_name VARCHAR(128) NULL,
    ADD COLUMN IF NOT EXISTS extraction_method VARCHAR(16) NULL;

CREATE INDEX IF NOT EXISTS idx_claims_document_version
    ON claims (document_version_id);

COMMIT;
