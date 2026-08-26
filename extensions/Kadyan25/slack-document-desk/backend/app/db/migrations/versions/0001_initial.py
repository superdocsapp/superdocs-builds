"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-08-06

"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "superdocs_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slack_user_id", sa.String(64), nullable=False, unique=True),
        sa.Column("superdocs_session_id", sa.String(256), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "document_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slack_user_id", sa.String(64), nullable=False),
        sa.Column("superdocs_document_id", sa.String(256), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("is_focused", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("slack_user_id", "superdocs_document_id", name="uq_document_link"),
    )

    op.create_table(
        "pending_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_id", sa.String(256), nullable=False, unique=True),
        sa.Column("slack_user_id", sa.String(64), nullable=False),
        sa.Column("superdocs_session_id", sa.String(256), nullable=False),
        sa.Column("superdocs_document_id", sa.String(256), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("pending_changes_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "recent_output",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slack_user_id", sa.String(64), nullable=False),
        sa.Column("job_id", sa.String(256), sa.ForeignKey("pending_jobs.job_id"), nullable=True),
        sa.Column("superdocs_document_id", sa.String(256), nullable=False),
        sa.Column("export_format", sa.String(16), nullable=False),
        sa.Column("download_url", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("recent_output")
    op.drop_table("pending_jobs")
    op.drop_table("document_links")
    op.drop_table("superdocs_sessions")
