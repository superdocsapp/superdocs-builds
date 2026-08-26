"""processed_changes table for idempotent approve/reject

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-06

"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "processed_changes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_id", sa.String(256), nullable=False),
        sa.Column("change_id", sa.String(256), nullable=False),
        sa.Column("approved", sa.Boolean(), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("job_id", "change_id", name="uq_processed_change"),
    )


def downgrade() -> None:
    op.drop_table("processed_changes")
