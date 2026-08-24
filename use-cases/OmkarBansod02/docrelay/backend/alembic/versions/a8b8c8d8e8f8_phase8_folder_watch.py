"""Add production Google Drive folder watch orchestration.

Revision ID: a8b8c8d8e8f8
Revises: f6a1c2d3e4b5
Create Date: 2026-08-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "a8b8c8d8e8f8"
down_revision: str | Sequence[str] | None = "f6a1c2d3e4b5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def _enum(*values: str, name: str) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, create_constraint=True)


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def upgrade() -> None:
    op.add_column(
        "watch_configs",
        sa.Column(
            "root_name",
            sa.String(length=512),
            server_default="Google Drive folder",
            nullable=False,
        ),
    )
    op.add_column(
        "watch_configs",
        sa.Column("interval_seconds", sa.Integer(), server_default="300", nullable=False),
    )
    op.add_column(
        "watch_configs", sa.Column("last_scan_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "watch_configs",
        sa.Column("last_successful_scan_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "watch_configs", sa.Column("next_scan_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "watch_configs",
        sa.Column(
            "last_scan_status",
            _enum("RUNNING", "SUCCEEDED", "FAILED", name="watch_scan_status"),
            nullable=True,
        ),
    )
    op.add_column(
        "watch_configs", sa.Column("last_error_code", sa.String(length=128), nullable=True)
    )
    op.create_check_constraint(
        "watch_interval_bounds",
        "watch_configs",
        "interval_seconds >= 60 AND interval_seconds <= 86400",
    )
    op.create_index(
        op.f("ix_watch_configs_next_scan_at"),
        "watch_configs",
        ["next_scan_at"],
        unique=False,
    )
    op.create_index(
        "ix_watch_configs_due",
        "watch_configs",
        ["enabled", "next_scan_at"],
        unique=False,
    )

    op.create_table(
        "watch_scans",
        sa.Column("watch_config_id", sa.Uuid(), nullable=False),
        sa.Column(
            "trigger",
            _enum("SCHEDULED", "MANUAL", name="watch_scan_trigger"),
            nullable=False,
        ),
        sa.Column(
            "status",
            _enum("RUNNING", "SUCCEEDED", "FAILED", name="watch_scan_status"),
            nullable=False,
        ),
        sa.Column("active_key", sa.String(length=16), nullable=True),
        sa.Column("lease_token", sa.Uuid(), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claim_generation", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("discovered_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("changed_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("unchanged_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("enqueued_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("skipped_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("failed_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("failure_code", sa.String(length=128), nullable=True),
        sa.Column("failure_detail", JSON_TYPE, nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("active_key IS NULL OR active_key = 'ACTIVE'", name="active_key_valid"),
        sa.CheckConstraint("claim_generation >= 1", name="watch_claim_generation_positive"),
        sa.ForeignKeyConstraint(["watch_config_id"], ["watch_configs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("watch_config_id", "active_key", name="uq_watch_scan_active"),
    )
    op.create_index(
        op.f("ix_watch_scans_watch_config_id"),
        "watch_scans",
        ["watch_config_id"],
        unique=False,
    )
    op.create_index(op.f("ix_watch_scans_status"), "watch_scans", ["status"], unique=False)
    op.create_index(
        op.f("ix_watch_scans_lease_expires_at"),
        "watch_scans",
        ["lease_expires_at"],
        unique=False,
    )

    op.create_table(
        "watched_items",
        sa.Column("watch_config_id", sa.Uuid(), nullable=False),
        sa.Column("provider_file_id", sa.String(length=255), nullable=False),
        sa.Column("cloud_document_id", sa.Uuid(), nullable=True),
        sa.Column("display_name", sa.String(length=512), nullable=False),
        sa.Column("mime_type", sa.String(length=255), nullable=False),
        sa.Column("provider_version", sa.String(length=128), nullable=False),
        sa.Column("provider_modified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("parent_folder_id", sa.String(length=255), nullable=False),
        sa.Column("ancestor_folder_ids", JSON_TYPE, nullable=False),
        sa.Column("current_in_scope", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("last_seen_scan_id", sa.Uuid(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_enqueued_provider_version", sa.String(length=128), nullable=True),
        sa.Column("last_enqueued_revision_id", sa.Text(), nullable=True),
        sa.Column("last_enqueued_run_id", sa.Uuid(), nullable=True),
        sa.Column(
            "write_authorization_state",
            _enum("REQUIRED", "AUTHORIZED", name="write_authorization_state"),
            nullable=False,
        ),
        sa.Column("write_authorization_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["watch_config_id"], ["watch_configs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["cloud_document_id"], ["cloud_documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["last_seen_scan_id"], ["watch_scans.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["last_enqueued_run_id"], ["sync_runs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "watch_config_id", "provider_file_id", name="uq_watched_item_watch_file"
        ),
    )
    for column in ("watch_config_id", "cloud_document_id", "last_seen_scan_id"):
        op.create_index(op.f(f"ix_watched_items_{column}"), "watched_items", [column], unique=False)
    op.create_index(
        "ix_watched_items_scope",
        "watched_items",
        ["watch_config_id", "current_in_scope"],
        unique=False,
    )

    op.create_table(
        "watch_document_versions",
        sa.Column("watched_item_id", sa.Uuid(), nullable=False),
        sa.Column("first_seen_scan_id", sa.Uuid(), nullable=False),
        sa.Column("provider_version", sa.String(length=128), nullable=False),
        sa.Column("provider_modified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status",
            _enum(
                "DISCOVERED",
                "NO_RULE",
                "ENQUEUE_PENDING",
                "ENQUEUED",
                "FAILED",
                name="watch_version_status",
            ),
            nullable=False,
        ),
        sa.Column("provider_revision_id", sa.Text(), nullable=True),
        sa.Column("folder_rule_id", sa.Uuid(), nullable=True),
        sa.Column("folder_rule_version", sa.Integer(), nullable=True),
        sa.Column("rule_snapshot", JSON_TYPE, nullable=True),
        sa.Column("sync_run_id", sa.Uuid(), nullable=True),
        sa.Column("failure_code", sa.String(length=128), nullable=True),
        sa.Column("failure_detail", JSON_TYPE, nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["watched_item_id"], ["watched_items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["first_seen_scan_id"], ["watch_scans.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["folder_rule_id"], ["folder_rules.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["sync_run_id"], ["sync_runs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "watched_item_id", "provider_version", name="uq_watch_document_item_version"
        ),
        sa.UniqueConstraint("sync_run_id", name="uq_watch_document_version_run"),
    )
    op.create_index(
        op.f("ix_watch_document_versions_watched_item_id"),
        "watch_document_versions",
        ["watched_item_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_watch_document_versions_first_seen_scan_id"),
        "watch_document_versions",
        ["first_seen_scan_id"],
        unique=False,
    )
    op.create_index(
        "ix_watch_document_versions_status",
        "watch_document_versions",
        ["watched_item_id", "status"],
        unique=False,
    )

    op.create_table(
        "watch_scan_items",
        sa.Column("watch_scan_id", sa.Uuid(), nullable=False),
        sa.Column("watched_item_id", sa.Uuid(), nullable=True),
        sa.Column("watch_document_version_id", sa.Uuid(), nullable=True),
        sa.Column("sync_run_id", sa.Uuid(), nullable=True),
        sa.Column("provider_file_id", sa.String(length=255), nullable=False),
        sa.Column("provider_version", sa.String(length=128), nullable=True),
        sa.Column("display_name", sa.String(length=512), nullable=False),
        sa.Column("mime_type", sa.String(length=255), nullable=False),
        sa.Column("ancestor_folder_ids", JSON_TYPE, nullable=False),
        sa.Column("discovery_kind", sa.String(length=32), nullable=False),
        sa.Column(
            "outcome",
            _enum(
                "ENQUEUED",
                "UNCHANGED",
                "NO_RULE",
                "UNSUPPORTED",
                "FAILED",
                "OUT_OF_SCOPE",
                name="watch_item_outcome",
            ),
            nullable=False,
        ),
        sa.Column("reason_code", sa.String(length=128), nullable=True),
        sa.Column("matched_rule_id", sa.Uuid(), nullable=True),
        sa.Column("matched_rule_version", sa.Integer(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["watch_scan_id"], ["watch_scans.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["watched_item_id"], ["watched_items.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["watch_document_version_id"],
            ["watch_document_versions.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["sync_run_id"], ["sync_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["matched_rule_id"], ["folder_rules.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("watch_scan_id", "provider_file_id", name="uq_watch_scan_item_file"),
    )
    op.create_index(
        op.f("ix_watch_scan_items_watch_scan_id"),
        "watch_scan_items",
        ["watch_scan_id"],
        unique=False,
    )

    op.create_table(
        "watch_run_links",
        sa.Column("watch_config_id", sa.Uuid(), nullable=False),
        sa.Column("watch_scan_id", sa.Uuid(), nullable=False),
        sa.Column("watched_item_id", sa.Uuid(), nullable=False),
        sa.Column("watch_document_version_id", sa.Uuid(), nullable=False),
        sa.Column("sync_run_id", sa.Uuid(), nullable=False),
        sa.Column("folder_rule_id", sa.Uuid(), nullable=False),
        sa.Column("folder_rule_version", sa.Integer(), nullable=False),
        sa.Column("rule_snapshot", JSON_TYPE, nullable=False),
        sa.Column(
            "write_authorization_state",
            _enum("REQUIRED", "AUTHORIZED", name="write_authorization_state"),
            nullable=False,
        ),
        sa.Column("write_authorization_checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "write_authorization_evidence",
            JSON_TYPE,
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["watch_config_id"], ["watch_configs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["watch_scan_id"], ["watch_scans.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["watched_item_id"], ["watched_items.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["watch_document_version_id"],
            ["watch_document_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["sync_run_id"], ["sync_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["folder_rule_id"], ["folder_rules.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("watch_document_version_id", name="uq_watch_run_link_version"),
        sa.UniqueConstraint("sync_run_id", name="uq_watch_run_link_run"),
    )
    for column in ("watch_config_id", "watch_scan_id", "sync_run_id"):
        op.create_index(
            op.f(f"ix_watch_run_links_{column}"), "watch_run_links", [column], unique=False
        )


def downgrade() -> None:
    for column in ("sync_run_id", "watch_scan_id", "watch_config_id"):
        op.drop_index(op.f(f"ix_watch_run_links_{column}"), table_name="watch_run_links")
    op.drop_table("watch_run_links")
    op.drop_index(op.f("ix_watch_scan_items_watch_scan_id"), table_name="watch_scan_items")
    op.drop_table("watch_scan_items")
    op.drop_index("ix_watch_document_versions_status", table_name="watch_document_versions")
    op.drop_index(
        op.f("ix_watch_document_versions_first_seen_scan_id"),
        table_name="watch_document_versions",
    )
    op.drop_index(
        op.f("ix_watch_document_versions_watched_item_id"),
        table_name="watch_document_versions",
    )
    op.drop_table("watch_document_versions")
    op.drop_index("ix_watched_items_scope", table_name="watched_items")
    for column in ("last_seen_scan_id", "cloud_document_id", "watch_config_id"):
        op.drop_index(op.f(f"ix_watched_items_{column}"), table_name="watched_items")
    op.drop_table("watched_items")
    op.drop_index(op.f("ix_watch_scans_lease_expires_at"), table_name="watch_scans")
    op.drop_index(op.f("ix_watch_scans_status"), table_name="watch_scans")
    op.drop_index(op.f("ix_watch_scans_watch_config_id"), table_name="watch_scans")
    op.drop_table("watch_scans")

    op.drop_index("ix_watch_configs_due", table_name="watch_configs")
    op.drop_index(op.f("ix_watch_configs_next_scan_at"), table_name="watch_configs")
    op.drop_constraint(
        op.f("ck_watch_configs_watch_interval_bounds"), "watch_configs", type_="check"
    )
    for column in (
        "last_error_code",
        "last_scan_status",
        "next_scan_at",
        "last_successful_scan_at",
        "last_scan_at",
        "interval_seconds",
        "root_name",
    ):
        op.drop_column("watch_configs", column)
