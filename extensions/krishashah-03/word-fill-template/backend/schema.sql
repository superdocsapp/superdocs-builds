-- ============================================================
-- AI Word Template Filler
-- PostgreSQL Database Schema
-- MVP: HR / Employee Salary Structure
-- ============================================================

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ============================================================
-- USERS
-- ============================================================

CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(150) NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================
-- TEMPLATES
-- ============================================================

CREATE TABLE templates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    name VARCHAR(255) NOT NULL,
    category VARCHAR(100) NOT NULL DEFAULT 'HR',

    description TEXT,

    -- Path / identifier of the Word template
    file_path TEXT NOT NULL,

    -- Template version
    version INTEGER NOT NULL DEFAULT 1,

    -- Expected fields for this template
    -- Example:
    -- {
    --   "employee.name": "string",
    --   "employee.ctc": "number",
    --   "employee.joining_date": "date"
    -- }
    schema JSONB NOT NULL DEFAULT '{}'::jsonb,

    is_active BOOLEAN NOT NULL DEFAULT TRUE,

    created_by UUID REFERENCES users(id) ON DELETE SET NULL,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_templates_category
ON templates(category);

CREATE INDEX idx_templates_active
ON templates(is_active);

-- ============================================================
-- TEMPLATE CONDITIONS
-- ============================================================

CREATE TABLE template_conditions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    template_id UUID NOT NULL
        REFERENCES templates(id)
        ON DELETE CASCADE,

    -- Example: employee.remote
    condition_key VARCHAR(255) NOT NULL,

    -- ==, !=, >, <, >=, <=
    operator VARCHAR(10) NOT NULL DEFAULT '=',

    -- Stored as JSON so values can be string/number/boolean
    expected_value JSONB NOT NULL,

    -- What happens when condition is satisfied
    -- include / exclude
    action VARCHAR(20) NOT NULL DEFAULT 'include',

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_template_conditions_template
ON template_conditions(template_id);

-- ============================================================
-- RECORDS
-- ============================================================

CREATE TABLE records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    template_id UUID
        REFERENCES templates(id)
        ON DELETE SET NULL,

    -- json / csv / email / text / form
    source_type VARCHAR(50) NOT NULL,

    -- Original input converted to JSON when possible
    raw_data JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- AI / parser normalized output
    normalized_data JSONB NOT NULL DEFAULT '{}'::jsonb,

    created_by UUID
        REFERENCES users(id)
        ON DELETE SET NULL,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_records_template
ON records(template_id);

CREATE INDEX idx_records_source_type
ON records(source_type);

CREATE INDEX idx_records_normalized_data
ON records USING GIN(normalized_data);

-- ============================================================
-- FILES
-- ============================================================

CREATE TABLE files (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Original filename
    file_name VARCHAR(500) NOT NULL,

    -- docx / csv / xlsx / pdf / image etc.
    mime_type VARCHAR(150),

    file_size BIGINT,

    -- For MVP this can point to local storage.
    -- Later this can be S3/R2/Supabase/etc.
    storage_path TEXT NOT NULL,

    uploaded_by UUID
        REFERENCES users(id)
        ON DELETE SET NULL,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_files_uploaded_by
ON files(uploaded_by);

-- ============================================================
-- DOCUMENT RUNS
-- ============================================================

CREATE TABLE document_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    template_id UUID NOT NULL
        REFERENCES templates(id)
        ON DELETE RESTRICT,

    record_id UUID
        REFERENCES records(id)
        ON DELETE SET NULL,

    -- draft / reviewing / completed / failed
    status VARCHAR(30) NOT NULL DEFAULT 'draft',

    -- Path to generated output
    output_file_path TEXT,

    -- Review information / metadata
    review_data JSONB NOT NULL DEFAULT '{}'::jsonb,

    error_message TEXT,

    created_by UUID
        REFERENCES users(id)
        ON DELETE SET NULL,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_document_runs_template
ON document_runs(template_id);

CREATE INDEX idx_document_runs_status
ON document_runs(status);

-- ============================================================
-- GAPS / MISSING INFORMATION
-- ============================================================

CREATE TABLE gaps (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    document_run_id UUID NOT NULL
        REFERENCES document_runs(id)
        ON DELETE CASCADE,

    -- Example: employee.notice_period
    field_key VARCHAR(255) NOT NULL,

    reason TEXT,

    resolved BOOLEAN NOT NULL DEFAULT FALSE,

    resolved_value JSONB,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMPTZ
);

CREATE INDEX idx_gaps_document_run
ON gaps(document_run_id);

CREATE INDEX idx_gaps_unresolved
ON gaps(resolved);

-- ============================================================
-- UPDATED_AT TRIGGER
-- ============================================================

CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER templates_updated_at
BEFORE UPDATE ON templates
FOR EACH ROW
EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER document_runs_updated_at
BEFORE UPDATE ON document_runs
FOR EACH ROW
EXECUTE FUNCTION update_updated_at();