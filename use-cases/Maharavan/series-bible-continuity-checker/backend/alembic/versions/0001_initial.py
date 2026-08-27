"""Explicit initial durable Series Bible schema."""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    ddl = """
    CREATE TABLE series (id UUID PRIMARY KEY, name VARCHAR(200) NOT NULL UNIQUE, description TEXT NOT NULL, version INTEGER NOT NULL, created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL);
    CREATE TABLE workflow_runs (id UUID PRIMARY KEY, series_id UUID NOT NULL REFERENCES series(id) ON DELETE CASCADE, current_stage VARCHAR(64) NOT NULL, status VARCHAR(32) NOT NULL, completed_stages JSON NOT NULL, state JSON NOT NULL, errors JSON NOT NULL, version INTEGER NOT NULL, created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL);
    CREATE INDEX ix_workflow_runs_series_id ON workflow_runs(series_id);
    CREATE TABLE documents (id UUID PRIMARY KEY, series_id UUID NOT NULL REFERENCES series(id) ON DELETE CASCADE, filename VARCHAR(255) NOT NULL, content_hash VARCHAR(64) NOT NULL, superdocs_session_id VARCHAR(256) NOT NULL UNIQUE, superdocs_document_id VARCHAR(256), status VARCHAR(32) NOT NULL, created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL, CONSTRAINT uq_document_series_hash UNIQUE(series_id, content_hash));
    CREATE INDEX ix_documents_series_id ON documents(series_id);
    CREATE TABLE chapters (id UUID PRIMARY KEY, document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE, number INTEGER NOT NULL, title VARCHAR(255) NOT NULL, created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL, CONSTRAINT uq_chapter_document_number UNIQUE(document_id, number));
    CREATE INDEX ix_chapters_document_id ON chapters(document_id);
    CREATE TABLE document_chunks (id UUID PRIMARY KEY, document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE, chapter_id UUID REFERENCES chapters(id) ON DELETE SET NULL, source_chunk_id VARCHAR(256) NOT NULL, section VARCHAR(255), page INTEGER, paragraph INTEGER, text TEXT NOT NULL, content_hash VARCHAR(64) NOT NULL, created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL, CONSTRAINT uq_document_source_chunk UNIQUE(document_id, source_chunk_id));
    CREATE INDEX ix_document_chunks_document_id ON document_chunks(document_id);
    CREATE INDEX ix_document_chunks_content_hash ON document_chunks(content_hash);
    CREATE TABLE bible_facts (id UUID PRIMARY KEY, series_id UUID NOT NULL REFERENCES series(id) ON DELETE CASCADE, kind VARCHAR(32) NOT NULL, entity VARCHAR(255) NOT NULL, attribute VARCHAR(255) NOT NULL, value TEXT NOT NULL, version INTEGER NOT NULL, is_current BOOLEAN NOT NULL, supersedes_id UUID REFERENCES bible_facts(id), confidence DOUBLE PRECISION NOT NULL, embedding vector(384), created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL, CONSTRAINT uq_fact_version UNIQUE(series_id, entity, attribute, version));
    CREATE INDEX ix_fact_lookup ON bible_facts(series_id, entity, attribute, is_current);
    CREATE TABLE characters (id UUID PRIMARY KEY, series_id UUID NOT NULL REFERENCES series(id) ON DELETE CASCADE, canonical_name VARCHAR(255) NOT NULL, created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL, CONSTRAINT uq_character_name UNIQUE(series_id, canonical_name));
    CREATE INDEX ix_characters_series_id ON characters(series_id);
    CREATE TABLE places (id UUID PRIMARY KEY, series_id UUID NOT NULL REFERENCES series(id) ON DELETE CASCADE, canonical_name VARCHAR(255) NOT NULL, created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL, CONSTRAINT uq_place_name UNIQUE(series_id, canonical_name));
    CREATE INDEX ix_places_series_id ON places(series_id);
    CREATE TABLE timeline_events (id UUID PRIMARY KEY, series_id UUID NOT NULL REFERENCES series(id) ON DELETE CASCADE, fact_id UUID NOT NULL UNIQUE REFERENCES bible_facts(id) ON DELETE CASCADE, sequence INTEGER, created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL);
    CREATE INDEX ix_timeline_events_series_id ON timeline_events(series_id);
    CREATE TABLE world_rules (id UUID PRIMARY KEY, series_id UUID NOT NULL REFERENCES series(id) ON DELETE CASCADE, fact_id UUID NOT NULL UNIQUE REFERENCES bible_facts(id) ON DELETE CASCADE, category VARCHAR(64) NOT NULL, created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL);
    CREATE INDEX ix_world_rules_series_id ON world_rules(series_id);
    CREATE TABLE continuity_findings (id UUID PRIMARY KEY, run_id UUID NOT NULL REFERENCES workflow_runs(id) ON DELETE CASCADE, series_id UUID NOT NULL REFERENCES series(id) ON DELETE CASCADE, existing_fact_id UUID REFERENCES bible_facts(id), fingerprint VARCHAR(64) NOT NULL, type VARCHAR(32) NOT NULL, entity VARCHAR(255) NOT NULL, attribute VARCHAR(255) NOT NULL, existing_value TEXT, new_value TEXT NOT NULL, explanation TEXT NOT NULL, confidence DOUBLE PRECISION NOT NULL, severity VARCHAR(16) NOT NULL, status VARCHAR(32) NOT NULL, new_fact JSON NOT NULL, version INTEGER NOT NULL, created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL, CONSTRAINT uq_finding_run_fingerprint UNIQUE(run_id, fingerprint));
    CREATE INDEX ix_continuity_findings_run_id ON continuity_findings(run_id);
    CREATE INDEX ix_continuity_findings_series_id ON continuity_findings(series_id);
    CREATE TABLE evidence (id UUID PRIMARY KEY, fact_id UUID REFERENCES bible_facts(id) ON DELETE CASCADE, finding_id UUID REFERENCES continuity_findings(id) ON DELETE CASCADE, document_id UUID NOT NULL REFERENCES documents(id), chapter VARCHAR(255) NOT NULL, section VARCHAR(255), page INTEGER, chunk_id VARCHAR(256) NOT NULL, exact_text TEXT NOT NULL, role VARCHAR(32) NOT NULL, created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL);
    CREATE INDEX ix_evidence_fact_id ON evidence(fact_id);
    CREATE INDEX ix_evidence_finding_id ON evidence(finding_id);
    CREATE TABLE review_decisions (id UUID PRIMARY KEY, finding_id UUID NOT NULL UNIQUE REFERENCES continuity_findings(id) ON DELETE CASCADE, actor VARCHAR(200) NOT NULL, resolution VARCHAR(32) NOT NULL, rationale TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL);
    CREATE TABLE proposed_changes (id UUID PRIMARY KEY, finding_id UUID NOT NULL REFERENCES continuity_findings(id), document_id UUID NOT NULL REFERENCES documents(id), instruction TEXT NOT NULL, superdocs_job_id VARCHAR(256) NOT NULL UNIQUE, superdocs_change_id VARCHAR(256), original_html TEXT, proposed_html TEXT, status VARCHAR(32) NOT NULL, version INTEGER NOT NULL, created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL);
    CREATE INDEX ix_proposed_changes_finding_id ON proposed_changes(finding_id);
    CREATE TABLE workflow_events (id UUID PRIMARY KEY, run_id UUID NOT NULL REFERENCES workflow_runs(id) ON DELETE CASCADE, stage VARCHAR(64) NOT NULL, status VARCHAR(32) NOT NULL, payload JSON NOT NULL, created_at TIMESTAMPTZ NOT NULL, CONSTRAINT uq_workflow_run_stage UNIQUE(run_id, stage));
    CREATE INDEX ix_workflow_events_run_id ON workflow_events(run_id);
    CREATE TABLE audit_events (id UUID PRIMARY KEY, run_id UUID REFERENCES workflow_runs(id), actor VARCHAR(200) NOT NULL, entity VARCHAR(100) NOT NULL, entity_id VARCHAR(100) NOT NULL, operation VARCHAR(64) NOT NULL, metadata JSON NOT NULL, created_at TIMESTAMPTZ NOT NULL);
    CREATE INDEX ix_audit_events_run_id ON audit_events(run_id);
    CREATE INDEX ix_audit_events_operation ON audit_events(operation);
    """
    for statement in ddl.split(";"):
        if statement.strip():
            op.execute(statement)


def downgrade() -> None:
    for table in ("audit_events", "workflow_events", "proposed_changes", "review_decisions", "evidence", "continuity_findings", "world_rules", "timeline_events", "places", "characters", "bible_facts", "document_chunks", "chapters", "documents", "workflow_runs", "series"):
        op.drop_table(table)
