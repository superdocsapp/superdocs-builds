"""google oauth and read-only baselines

Revision ID: 8f2d7c9a1e4b
Revises: 4db6c7eb34db
Create Date: 2026-08-07 19:00:00 UTC
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "8f2d7c9a1e4b"
down_revision: str | Sequence[str] | None = "4db6c7eb34db"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.drop_constraint(
        op.f("ck_cloud_connections_connection_status"),
        "cloud_connections",
        type_="check",
    )
    op.alter_column(
        "cloud_connections",
        "status",
        existing_type=sa.String(length=7),
        type_=sa.String(length=15),
        existing_nullable=False,
    )
    op.execute(
        sa.text(
            """
            UPDATE cloud_connections
            SET status = CASE status
              WHEN 'ACTIVE' THEN 'CONNECTED'
              WHEN 'REVOKED' THEN 'DISCONNECTED'
              WHEN 'ERROR' THEN 'INVALID'
              ELSE status
            END
            """
        )
    )
    op.create_check_constraint(
        op.f("ck_cloud_connections_connection_status"),
        "cloud_connections",
        "status IN ('PENDING', 'CONNECTED', 'DISCONNECTED', 'REAUTH_REQUIRED', 'INVALID')",
    )
    op.add_column(
        "cloud_connections",
        sa.Column("status_reason", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "cloud_connections",
        sa.Column("disconnected_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "oauth_credentials",
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("encrypted_payload", sa.Text(), nullable=False),
        sa.Column("encryption_key_version", sa.String(length=64), nullable=False),
        sa.Column("access_token_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("refresh_token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_refreshed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["cloud_connections.id"],
            name=op.f("fk_oauth_credentials_connection_id_cloud_connections"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_oauth_credentials")),
        sa.UniqueConstraint("connection_id", name=op.f("uq_oauth_credential_connection")),
    )
    op.create_index(
        op.f("ix_oauth_credentials_connection_id"),
        "oauth_credentials",
        ["connection_id"],
        unique=False,
    )

    op.create_table(
        "google_oauth_states",
        sa.Column("owner_subject", sa.String(length=255), nullable=False),
        sa.Column("state_sha256", sa.String(length=64), nullable=False),
        sa.Column("browser_nonce_sha256", sa.String(length=64), nullable=False),
        sa.Column("code_verifier_ciphertext", sa.Text(), nullable=False),
        sa.Column("encryption_key_version", sa.String(length=64), nullable=False),
        sa.Column("requested_scopes", JSON_TYPE, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_google_oauth_states")),
        sa.UniqueConstraint("state_sha256", name=op.f("uq_google_oauth_states_state_sha256")),
    )
    op.create_index(
        op.f("ix_google_oauth_states_owner_subject"),
        "google_oauth_states",
        ["owner_subject"],
        unique=False,
    )
    op.create_index(
        op.f("ix_google_oauth_states_expires_at"),
        "google_oauth_states",
        ["expires_at"],
        unique=False,
    )

    op.create_table(
        "google_baseline_captures",
        sa.Column("cloud_document_id", sa.Uuid(), nullable=False),
        sa.Column("provider_revision_id", sa.Text(), nullable=False),
        sa.Column("native_raw_sha256", sa.String(length=64), nullable=False),
        sa.Column("native_canonical_sha256", sa.String(length=64), nullable=False),
        sa.Column("exported_docx_sha256", sa.String(length=64), nullable=False),
        sa.Column("exported_docx_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("canonicalizer_version", sa.String(length=128), nullable=False),
        sa.Column("canonical_payload", JSON_TYPE, nullable=False),
        sa.Column("capability_evidence", JSON_TYPE, nullable=False),
        sa.Column("parent_ids", JSON_TYPE, nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("capture_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider_evidence", JSON_TYPE, nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "attempt_count >= 1",
            name=op.f("ck_google_baseline_captures_google_baseline_attempt_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["cloud_document_id"],
            ["cloud_documents.id"],
            name=op.f("fk_google_baseline_captures_cloud_document_id_cloud_documents"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_google_baseline_captures")),
    )
    op.create_index(
        op.f("ix_google_baseline_captures_cloud_document_id"),
        "google_baseline_captures",
        ["cloud_document_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_google_baseline_document_revision"),
        "google_baseline_captures",
        ["cloud_document_id", "provider_revision_id"],
        unique=False,
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            sa.text(
                """
                CREATE TRIGGER trg_google_baseline_captures_immutable
                BEFORE UPDATE ON google_baseline_captures FOR EACH ROW
                EXECUTE FUNCTION docrelay_reject_immutable_update()
                """
            )
        )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_google_baseline_document_revision"),
        table_name="google_baseline_captures",
    )
    op.drop_index(
        op.f("ix_google_baseline_captures_cloud_document_id"),
        table_name="google_baseline_captures",
    )
    op.drop_table("google_baseline_captures")
    op.drop_index(op.f("ix_google_oauth_states_expires_at"), table_name="google_oauth_states")
    op.drop_index(op.f("ix_google_oauth_states_owner_subject"), table_name="google_oauth_states")
    op.drop_table("google_oauth_states")
    op.drop_index(op.f("ix_oauth_credentials_connection_id"), table_name="oauth_credentials")
    op.drop_table("oauth_credentials")
    op.drop_column("cloud_connections", "disconnected_at")
    op.drop_column("cloud_connections", "status_reason")
    op.drop_constraint(
        op.f("ck_cloud_connections_connection_status"),
        "cloud_connections",
        type_="check",
    )
    op.execute(
        sa.text(
            """
            UPDATE cloud_connections
            SET status = CASE status
              WHEN 'CONNECTED' THEN 'ACTIVE'
              WHEN 'DISCONNECTED' THEN 'REVOKED'
              WHEN 'REAUTH_REQUIRED' THEN 'ERROR'
              WHEN 'INVALID' THEN 'ERROR'
              ELSE status
            END
            """
        )
    )
    op.alter_column(
        "cloud_connections",
        "status",
        existing_type=sa.String(length=15),
        type_=sa.String(length=7),
        existing_nullable=False,
    )
    op.create_check_constraint(
        op.f("ck_cloud_connections_connection_status"),
        "cloud_connections",
        "status IN ('PENDING', 'ACTIVE', 'REVOKED', 'ERROR')",
    )
