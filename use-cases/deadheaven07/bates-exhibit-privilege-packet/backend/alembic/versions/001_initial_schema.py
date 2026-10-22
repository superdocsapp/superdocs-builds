"""Initial schema

Revision ID: 001
Revises: 
Create Date: 2024-01-15 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "packets",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.String(2000), nullable=True),
        sa.Column("bates_prefix", sa.String(50), nullable=False, server_default="CASE-"),
        sa.Column("bates_start_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("bates_padding", sa.Integer(), nullable=False, server_default="6"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("packet_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column("original_filename", sa.String(512), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("document_type", sa.String(20), nullable=False, server_default="unknown"),
        sa.Column("page_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("processing_status", sa.String(30), nullable=False, server_default="queued"),
        sa.Column("processing_error", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_completed_step", sa.String(100), nullable=True),
        sa.Column("original_sha256", sa.String(64), nullable=False),
        sa.Column("processed_sha256", sa.String(64), nullable=True),
        sa.Column("final_sha256", sa.String(64), nullable=True),
        sa.Column("superdocs_session_id", sa.String(256), nullable=True),
        sa.Column("superdocs_document_id", sa.String(256), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("description_source", sa.String(100), nullable=True),
        sa.Column("description_generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_searchable", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["packet_id"], ["packets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_documents_packet_order", "documents", ["packet_id", "display_order"])
    op.create_index("ix_documents_sha256", "documents", ["sha256"])
    op.create_index("ix_documents_status", "documents", ["processing_status"])

    op.create_table(
        "pages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("width", sa.Float(), nullable=True),
        sa.Column("height", sa.Float(), nullable=True),
        sa.Column("rotation", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("has_text", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("extracted_text", sa.String(1000000), nullable=True),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_pages_document_number", "pages", ["document_id", "page_number"], unique=True)

    op.create_table(
        "bates_assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("packet_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("page_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("bates_number", sa.Integer(), nullable=False),
        sa.Column("bates_label", sa.String(100), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["packet_id"], ["packets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["page_id"], ["pages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("packet_id", "bates_number", name="uq_bates_packet_number"),
        sa.UniqueConstraint("packet_id", "document_id", "page_number", name="uq_bates_packet_doc_page"),
    )
    op.create_index("ix_bates_packet_doc", "bates_assignments", ["packet_id", "document_id"])
    op.create_index("ix_bates_number", "bates_assignments", ["bates_number"])

    op.create_table(
        "privilege_decisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("packet_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("category", sa.String(20), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("bates_start", sa.String(100), nullable=True),
        sa.Column("bates_end", sa.String(100), nullable=True),
        sa.Column("reviewer", sa.String(255), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["packet_id"], ["packets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_privilege_packet_doc", "privilege_decisions", ["packet_id", "document_id"], unique=True)
    op.create_index("ix_privilege_status", "privilege_decisions", ["status"])

    op.create_table(
        "redaction_candidates",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(20), nullable=False),
        sa.Column("matched_text", sa.String(500), nullable=False),
        sa.Column("context_before", sa.String(200), nullable=True),
        sa.Column("context_after", sa.String(200), nullable=True),
        sa.Column("x0", sa.Float(), nullable=True),
        sa.Column("y0", sa.Float(), nullable=True),
        sa.Column("x1", sa.Float(), nullable=True),
        sa.Column("y1", sa.Float(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="proposed"),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("proposed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("proposed_by", sa.String(255), nullable=False, server_default="system"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_redaction_doc_page", "redaction_candidates", ["document_id", "page_number"])
    op.create_index("ix_redaction_status", "redaction_candidates", ["status"])

    op.create_table(
        "redaction_approvals",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("candidate_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("approver", sa.String(255), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applied_by", sa.String(255), nullable=True),
        sa.Column("verified_by", sa.String(255), nullable=True),
        sa.Column("verification_passed", sa.Boolean(), nullable=True),
        sa.Column("verification_details", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["candidate_id"], ["redaction_candidates.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("candidate_id"),
    )
    op.create_index("ix_redaction_approval_status", "redaction_approvals", ["status"])

    op.create_table(
        "audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("packet_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("user_id", sa.String(255), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["packet_id"], ["packets.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_packet_time", "audit_events", ["packet_id", "timestamp"])
    op.create_index("ix_audit_document_time", "audit_events", ["document_id", "timestamp"])
    op.create_index("ix_audit_type_time", "audit_events", ["event_type", "timestamp"])

    op.create_table(
        "manifests",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("packet_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("total_pages", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_documents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("bates_start", sa.String(100), nullable=True),
        sa.Column("bates_end", sa.String(100), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("validation_passed", sa.Boolean(), nullable=True),
        sa.Column("validation_details", postgresql.JSONB(), nullable=True),
        sa.Column("final_packet_sha256", sa.String(64), nullable=True),
        sa.Column("final_packet_path", sa.String(512), nullable=True),
        sa.ForeignKeyConstraint(["packet_id"], ["packets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("packet_id"),
    )

    op.create_table(
        "manifest_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("manifest_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("exhibit_identifier", sa.String(50), nullable=False),
        sa.Column("bates_start", sa.String(100), nullable=False),
        sa.Column("bates_end", sa.String(100), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("original_sha256", sa.String(64), nullable=False),
        sa.Column("processed_sha256", sa.String(64), nullable=True),
        sa.Column("final_sha256", sa.String(64), nullable=True),
        sa.Column("description", sa.String(2000), nullable=True),
        sa.Column("privilege_status", sa.String(50), nullable=True),
        sa.Column("privilege_category", sa.String(50), nullable=True),
        sa.Column("privilege_reason", sa.String(2000), nullable=True),
        sa.Column("applied_redactions", postgresql.JSONB(), nullable=True),
        sa.Column("final_file_path", sa.String(512), nullable=True),
        sa.ForeignKeyConstraint(["manifest_id"], ["manifests.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_manifest_entry_manifest", "manifest_entries", ["manifest_id"])
    op.create_index("ix_manifest_entry_exhibit", "manifest_entries", ["exhibit_identifier"])


def downgrade() -> None:
    op.drop_table("manifest_entries")
    op.drop_table("manifests")
    op.drop_table("audit_events")
    op.drop_table("redaction_approvals")
    op.drop_table("redaction_candidates")
    op.drop_table("privilege_decisions")
    op.drop_table("bates_assignments")
    op.drop_table("pages")
    op.drop_table("documents")
    op.drop_table("packets")