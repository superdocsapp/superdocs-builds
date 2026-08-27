"""per-document SuperDocs session — each shared file gets its own session

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-27

SuperDocs' upload-into-an-existing-session overwrites that session's single
document in place (same durable id, new content) rather than opening a new
document — so reusing one session per Slack user glued every share onto the first
document the session ever had. Each DocumentLink now carries its own session so a
share creates a genuinely distinct, correctly-tracked document. Nullable so
pre-existing links (which used the per-user session) don't break the migration.
"""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "document_links",
        sa.Column("superdocs_session_id", sa.String(256), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("document_links", "superdocs_session_id")
