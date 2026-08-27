-- The schema as it shipped.
--
-- Never edit a migration that has been applied: the runner records a checksum and
-- refuses to start if one changes underneath a deployment that already ran it. Add a
-- new numbered file instead.

CREATE TABLE IF NOT EXISTS inspections (
    id             UUID PRIMARY KEY,
    address_line   TEXT        NOT NULL,
    city           TEXT        NOT NULL,
    postcode       TEXT        NOT NULL DEFAULT '',
    year_built     INTEGER,
    property_type  TEXT        NOT NULL DEFAULT '',
    inspector_name TEXT        NOT NULL,
    licence_number TEXT        NOT NULL DEFAULT '',
    firm_name      TEXT        NOT NULL DEFAULT '',
    inspected_on   DATE        NOT NULL,
    template_key   TEXT        NOT NULL DEFAULT 'buyer_summary',
    stage          TEXT        NOT NULL DEFAULT 'draft',
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS findings (
    id             UUID PRIMARY KEY,
    inspection_id  UUID        NOT NULL REFERENCES inspections(id) ON DELETE CASCADE,
    system_key     TEXT        NOT NULL,
    severity_key   TEXT        NOT NULL,
    location       TEXT        NOT NULL DEFAULT '',
    observation    TEXT        NOT NULL,
    recommendation TEXT        NOT NULL DEFAULT '',
    plain_language TEXT        NOT NULL DEFAULT '',
    position       INTEGER     NOT NULL DEFAULT 0,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS findings_by_inspection ON findings (inspection_id, position);

CREATE TABLE IF NOT EXISTS photos (
    id            UUID PRIMARY KEY,
    finding_id    UUID        NOT NULL REFERENCES findings(id) ON DELETE CASCADE,
    sha256        TEXT        NOT NULL,
    filename      TEXT        NOT NULL,
    content_type  TEXT        NOT NULL,
    size_bytes    INTEGER     NOT NULL,
    width         INTEGER     NOT NULL DEFAULT 0,
    height        INTEGER     NOT NULL DEFAULT 0,
    caption       TEXT        NOT NULL DEFAULT '',
    position      INTEGER     NOT NULL DEFAULT 0,
    bytes         BYTEA       NOT NULL,
    thumbnail     BYTEA,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS photos_by_finding ON photos (finding_id, position);

-- The upload cache. Keyed by content, because that is what a photograph's identity is:
-- the same bytes are the same photograph however many findings or runs reference them, and
-- an upload that has been paid for once is never paid for again.
CREATE TABLE IF NOT EXISTS photo_uploads (
    sha256     TEXT PRIMARY KEY,
    remote_url TEXT        NOT NULL,
    uploaded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Every proposal the AI made and what was decided about it, including the rail's verdict.
-- Kept because "why does the report say this" must be answerable after the fact.
CREATE TABLE IF NOT EXISTS proposals (
    id            UUID PRIMARY KEY,
    inspection_id UUID        NOT NULL REFERENCES inspections(id) ON DELETE CASCADE,
    finding_id    UUID        REFERENCES findings(id) ON DELETE SET NULL,
    job_id        TEXT        NOT NULL DEFAULT '',
    change_id     TEXT        NOT NULL DEFAULT '',
    old_text      TEXT        NOT NULL DEFAULT '',
    new_text      TEXT        NOT NULL DEFAULT '',
    rail_clean    BOOLEAN     NOT NULL DEFAULT TRUE,
    rail_breaches JSONB       NOT NULL DEFAULT '[]'::jsonb,
    decision      TEXT        NOT NULL DEFAULT 'pending',
    decided_at    TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS proposals_by_inspection ON proposals (inspection_id);
