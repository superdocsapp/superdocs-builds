"""Add SuperDocs intelligence provenance columns to redaction_candidates and
privilege_decisions.

Revision ID: 003
Revises: 002
Create Date: 2026-08-16 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "redaction_candidates",
        sa.Column("superdocs_change_id", sa.String(256), nullable=True),
    )
    op.add_column(
        "privilege_decisions",
        sa.Column("proposed_by", sa.String(255), nullable=True),
    )
    op.add_column(
        "privilege_decisions",
        sa.Column("superdocs_change_id", sa.String(256), nullable=True),
    )
    op.create_index(
        "ix_redaction_superdocs_change", "redaction_candidates", ["superdocs_change_id"]
    )


def downgrade():
    op.drop_index("ix_redaction_superdocs_change", table_name="redaction_candidates")
    op.drop_column("privilege_decisions", "superdocs_change_id")
    op.drop_column("privilege_decisions", "proposed_by")
    op.drop_column("redaction_candidates", "superdocs_change_id")