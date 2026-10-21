"""Phase 8: memo sections and document roles

Revision ID: 0006_phase8_memo_sections
Revises: 0005_phase7_superdocs
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0006_phase8_memo_sections"
down_revision = "0005_phase7_superdocs"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "memo_sections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("workflow_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workflow_runs.id"), nullable=False),
        sa.Column("section_type", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("section_order", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("source_attribution", sa.JSON(), nullable=True),
        sa.Column("analyst_reasoning", sa.Text(), nullable=True),
        sa.Column("evidence_refs", sa.JSON(), nullable=True),
        sa.Column("confidence", sa.String(), nullable=True),
        sa.Column("baseline_section_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("memo_sections.id"), nullable=True),
        sa.Column("structured_data", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("ix_memo_sections_run_order", "memo_sections", ["workflow_run_id", "section_order"])
    op.create_index("uq_memo_sections_run_type", "memo_sections", ["workflow_run_id", "section_type"], unique=True)

    op.add_column("documents", sa.Column("document_role", sa.String(), nullable=False, server_default="product_spec"))
    op.create_index("ix_documents_workspace_role", "documents", ["workspace_id", "document_role"])


def downgrade():
    op.drop_index("ix_documents_workspace_role", table_name="documents")
    op.drop_column("documents", "document_role")
    op.drop_index("uq_memo_sections_run_type", table_name="memo_sections")
    op.drop_index("ix_memo_sections_run_order", table_name="memo_sections")
    op.drop_table("memo_sections")
