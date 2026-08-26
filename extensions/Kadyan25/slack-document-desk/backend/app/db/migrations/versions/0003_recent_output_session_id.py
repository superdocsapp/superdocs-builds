"""add superdocs_session_id to recent_output (needed to re-export past a link's TTL)

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-06

"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "recent_output",
        sa.Column("superdocs_session_id", sa.String(256), nullable=False, server_default=""),
    )
    op.alter_column("recent_output", "superdocs_session_id", server_default=None)


def downgrade() -> None:
    op.drop_column("recent_output", "superdocs_session_id")
