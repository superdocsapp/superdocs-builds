"""Add durable Phase 6 conflict decisions.

Revision ID: f6a1c2d3e4b5
Revises: e5b4a9c2d7f0
Create Date: 2026-08-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "f6a1c2d3e4b5"
down_revision: str | Sequence[str] | None = "e5b4a9c2d7f0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "write_conflicts",
        sa.Column("sync_run_id", sa.Uuid(), nullable=False),
        sa.Column("write_plan_id", sa.Uuid(), nullable=False),
        sa.Column("backup_id", sa.Uuid(), nullable=True),
        sa.Column("baseline_revision_id", sa.Text(), nullable=False),
        sa.Column("latest_revision_id", sa.Text(), nullable=True),
        sa.Column("detection_stage", sa.String(length=128), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "safe_evidence",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "decision",
            sa.Enum(
                "CANCEL",
                "REVIEW_LATEST",
                name="conflict_choice",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=True,
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by_subject", sa.String(length=255), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["backup_id"], ["backups.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["sync_run_id"], ["sync_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["write_plan_id"], ["write_plans.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sync_run_id", name="uq_write_conflict_run"),
    )
    op.create_index(
        op.f("ix_write_conflicts_sync_run_id"),
        "write_conflicts",
        ["sync_run_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_write_conflicts_sync_run_id"), table_name="write_conflicts")
    op.drop_table("write_conflicts")
