-- Migration 004: Create claims and source_locations tables
-- Requirements: 2.1, 2.2, 2.4, 2.5, 4.2, 7.1, 7.2, 7.3

BEGIN;

-- Create claims table
CREATE TABLE IF NOT EXISTS claims (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_version_id UUID NOT NULL REFERENCES document_versions(id) ON DELETE RESTRICT,
    run_id UUID NOT NULL REFERENCES runs(id) ON DELETE RESTRICT,
    extracted_text VARCHAR(10000) NOT NULL,
    claim_type VARCHAR(128) NOT NULL,
    confidence NUMERIC(4,3) NOT NULL,
    extracted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_claims_confidence CHECK (confidence >= 0.0 AND confidence <= 1.0)
);

-- Create source_locations table
CREATE TABLE IF NOT EXISTS source_locations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    claim_id UUID NOT NULL REFERENCES claims(id) ON DELETE RESTRICT,
    document_version_id UUID NOT NULL REFERENCES document_versions(id) ON DELETE RESTRICT,
    page_number INTEGER NULL,
    section_id VARCHAR(256) NULL,
    start_offset INTEGER NOT NULL,
    end_offset INTEGER NOT NULL,
    clause_ref VARCHAR(512) NULL,
    CONSTRAINT chk_source_locations_page_number CHECK (page_number >= 1 OR page_number IS NULL),
    CONSTRAINT chk_source_locations_start_offset CHECK (start_offset >= 0),
    CONSTRAINT chk_source_locations_end_offset CHECK (end_offset >= 0),
    CONSTRAINT chk_source_locations_offset_order CHECK (start_offset < end_offset)
);

COMMIT;
