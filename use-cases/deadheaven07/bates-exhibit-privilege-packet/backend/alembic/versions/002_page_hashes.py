"""Add page_hashes and merkle_root to manifest_entries

Revision ID: 002
Revises: 001
Create Date: 2025-01-15 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "manifest_entries",
        sa.Column("page_hashes", sa.JSON(), nullable=True, default=list),
    )
    op.add_column(
        "manifest_entries",
        sa.Column("merkle_root", sa.String(64), nullable=True),
    )


def downgrade():
    op.drop_column("manifest_entries", "page_hashes")
    op.drop_column("manifest_entries", "merkle_root")