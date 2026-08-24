"""phase3 SuperDocs orchestration

Revision ID: c6a8d31f4b2e
Revises: 8f2d7c9a1e4b
Create Date: 2026-08-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c6a8d31f4b2e"
down_revision: str | None = "8f2d7c9a1e4b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SYNC_RUN_STATES = (
    "QUEUED",
    "BASELINING",
    "EDITING",
    "AWAITING_REVIEW",
    "REVIEWED_EXPORT_READY",
    "READY_TO_COMMIT",
    "PREVIEW_READY",
    "COMMITTING",
    "VERIFYING",
    "SUCCEEDED",
    "CONFLICT",
    "UNSUPPORTED",
    "SKIPPED",
    "EXPIRED",
    "COMMIT_OUTCOME_UNKNOWN",
    "VERIFICATION_FAILED",
    "FAILED",
    "CANCELLED",
)

EFFECT_TYPES = (
    "SUPERDOCS_UPLOAD",
    "SUPERDOCS_JOB_START",
    "SUPERDOCS_REVIEW_SUBMISSION",
    "SUPERDOCS_CONTINUE",
    "SUPERDOCS_FOCUS",
    "GOOGLE_BACKUP_COPY",
    "GOOGLE_BATCH_UPDATE",
)


def _in_constraint(column: str, values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({quoted})"


def upgrade() -> None:
    op.alter_column("sync_runs", "folder_rule_id", existing_type=sa.Uuid(), nullable=True)
    op.alter_column("sync_runs", "folder_rule_version", existing_type=sa.Integer(), nullable=True)
    op.add_column(
        "source_snapshots", sa.Column("artifact_reference", sa.String(length=512), nullable=True)
    )
    op.alter_column(
        "superdocs_documents",
        "upload_version_id",
        existing_type=sa.String(length=255),
        nullable=True,
    )
    op.add_column("proposed_changes", sa.Column("ordinal", sa.Integer(), nullable=True))
    op.create_check_constraint(
        "ordinal_positive",
        "proposed_changes",
        "ordinal IS NULL OR ordinal >= 1",
    )
    op.create_unique_constraint(
        "uq_proposed_change_round_ordinal",
        "proposed_changes",
        ["review_round_id", "ordinal"],
    )

    op.drop_constraint(op.f("ck_sync_runs_sync_run_state"), "sync_runs", type_="check")
    op.create_check_constraint(
        "sync_run_state",
        "sync_runs",
        _in_constraint("state", SYNC_RUN_STATES),
    )
    op.drop_constraint(op.f("ck_external_effects_effect_type"), "external_effects", type_="check")
    op.alter_column(
        "external_effects",
        "effect_type",
        existing_type=sa.String(length=19),
        type_=sa.String(length=27),
        existing_nullable=False,
    )
    op.create_check_constraint(
        "effect_type",
        "external_effects",
        _in_constraint("effect_type", EFFECT_TYPES),
    )

    op.create_table(
        "superdocs_exports",
        sa.Column("sync_run_id", sa.Uuid(), nullable=False),
        sa.Column("source_snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("superdocs_session_id", sa.Uuid(), nullable=False),
        sa.Column("superdocs_document_id", sa.Uuid(), nullable=False),
        sa.Column("superdocs_job_id", sa.Uuid(), nullable=False),
        sa.Column("artifact_reference", sa.String(length=512), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=False),
        sa.Column("content_disposition", sa.String(length=1024), nullable=True),
        sa.Column("warnings_raw", sa.Text(), nullable=True),
        sa.Column(
            "warnings",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
        sa.Column("final_version_id", sa.String(length=255), nullable=True),
        sa.Column("exported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["sync_run_id"],
            ["sync_runs.id"],
            name=op.f("fk_superdocs_exports_sync_run_id_sync_runs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_snapshot_id"],
            ["source_snapshots.id"],
            name=op.f("fk_superdocs_exports_source_snapshot_id_source_snapshots"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["superdocs_session_id"],
            ["superdocs_sessions.id"],
            name=op.f("fk_superdocs_exports_superdocs_session_id_superdocs_sessions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["superdocs_document_id"],
            ["superdocs_documents.id"],
            name=op.f("fk_superdocs_exports_superdocs_document_id_superdocs_documents"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["superdocs_job_id"],
            ["superdocs_jobs.id"],
            name=op.f("fk_superdocs_exports_superdocs_job_id_superdocs_jobs"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_superdocs_exports")),
        sa.UniqueConstraint("superdocs_job_id", name="uq_superdocs_export_job"),
        sa.UniqueConstraint("artifact_reference", name="uq_superdocs_export_artifact_reference"),
    )
    op.create_index(
        op.f("ix_superdocs_exports_sync_run_id"),
        "superdocs_exports",
        ["sync_run_id"],
        unique=False,
    )
    op.execute(
        """
        CREATE TRIGGER trg_superdocs_exports_immutable
        BEFORE UPDATE OR DELETE ON superdocs_exports
        FOR EACH ROW EXECUTE FUNCTION docrelay_reject_immutable_update()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_superdocs_exports_immutable ON superdocs_exports")
    op.drop_index(op.f("ix_superdocs_exports_sync_run_id"), table_name="superdocs_exports")
    op.drop_table("superdocs_exports")

    op.drop_constraint(op.f("ck_external_effects_effect_type"), "external_effects", type_="check")
    op.alter_column(
        "external_effects",
        "effect_type",
        existing_type=sa.String(length=27),
        type_=sa.String(length=19),
        existing_nullable=False,
    )
    op.create_check_constraint(
        "effect_type",
        "external_effects",
        _in_constraint(
            "effect_type",
            ("SUPERDOCS_JOB_START", "GOOGLE_BACKUP_COPY", "GOOGLE_BATCH_UPDATE"),
        ),
    )
    op.drop_constraint(op.f("ck_sync_runs_sync_run_state"), "sync_runs", type_="check")
    op.create_check_constraint(
        "sync_run_state",
        "sync_runs",
        _in_constraint(
            "state", tuple(value for value in SYNC_RUN_STATES if value != "REVIEWED_EXPORT_READY")
        ),
    )

    op.alter_column(
        "superdocs_documents",
        "upload_version_id",
        existing_type=sa.String(length=255),
        nullable=False,
    )
    op.drop_constraint("uq_proposed_change_round_ordinal", "proposed_changes", type_="unique")
    op.drop_constraint(
        op.f("ck_proposed_changes_ordinal_positive"), "proposed_changes", type_="check"
    )
    op.drop_column("proposed_changes", "ordinal")
    op.drop_column("source_snapshots", "artifact_reference")
    op.alter_column("sync_runs", "folder_rule_version", existing_type=sa.Integer(), nullable=False)
    op.alter_column("sync_runs", "folder_rule_id", existing_type=sa.Uuid(), nullable=False)
