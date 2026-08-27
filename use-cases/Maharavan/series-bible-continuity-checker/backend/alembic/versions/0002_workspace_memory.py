"""Episodic memory, chat persistence, and chunk-level semantic retrieval."""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    ddl = """
    ALTER TABLE document_chunks ADD COLUMN embedding vector(384);
    CREATE TABLE story_events (id UUID PRIMARY KEY, series_id UUID NOT NULL REFERENCES series(id) ON DELETE CASCADE, run_id UUID REFERENCES workflow_runs(id), document_id UUID REFERENCES documents(id), chapter_id UUID REFERENCES chapters(id), finding_id UUID REFERENCES continuity_findings(id), event_type VARCHAR(64) NOT NULL, description TEXT NOT NULL, actor VARCHAR(200) NOT NULL, source VARCHAR(255), embedding vector(384), created_at TIMESTAMPTZ NOT NULL);
    CREATE INDEX ix_story_events_series_id ON story_events(series_id);
    CREATE INDEX ix_story_events_run_id ON story_events(run_id);
    CREATE INDEX ix_story_events_event_type ON story_events(event_type);
    CREATE TABLE chat_sessions (id UUID PRIMARY KEY, series_id UUID NOT NULL REFERENCES series(id) ON DELETE CASCADE, title VARCHAR(255) NOT NULL, created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL);
    CREATE INDEX ix_chat_sessions_series_id ON chat_sessions(series_id);
    CREATE TABLE chat_messages (id UUID PRIMARY KEY, session_id UUID NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE, series_id UUID NOT NULL REFERENCES series(id) ON DELETE CASCADE, role VARCHAR(16) NOT NULL, content TEXT NOT NULL, citations JSON NOT NULL, grounded BOOLEAN NOT NULL, created_at TIMESTAMPTZ NOT NULL);
    CREATE INDEX ix_chat_messages_session_id ON chat_messages(session_id);
    CREATE INDEX ix_chat_messages_series_id ON chat_messages(series_id);
    """
    for statement in ddl.split(";"):
        if statement.strip():
            op.execute(statement)


def downgrade() -> None:
    for table in ("chat_messages", "chat_sessions", "story_events"):
        op.drop_table(table)
    op.execute("ALTER TABLE document_chunks DROP COLUMN embedding")
