"""add evidence and citations tables

Revision ID: a1b2c3d4e5f6
Revises: 50f1fb7be338
Create Date: 2026-08-08 12:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '50f1fb7be338'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'evidence',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('workflow_run_id', sa.UUID(), sa.ForeignKey('workflow_runs.id'), nullable=False),
        sa.Column('document_id', sa.UUID(), sa.ForeignKey('documents.id'), nullable=False),
        sa.Column('chunk_id', sa.UUID(), sa.ForeignKey('document_chunks.id'), nullable=True),
        sa.Column('extracted_text', sa.Text(), nullable=False),
        sa.Column('evidence_type', sa.String(), nullable=False),
        sa.Column('page_number', sa.String(), nullable=True),
        sa.Column('relevance_score', sa.Float(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_evidence_workflow_run_id', 'evidence', ['workflow_run_id'])
    op.create_index('ix_evidence_document_id', 'evidence', ['document_id'])
    op.create_index('ix_evidence_chunk_id', 'evidence', ['chunk_id'])
    op.create_index('ix_evidence_run_document', 'evidence', ['workflow_run_id', 'document_id'])

    op.create_table(
        'citations',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('claim_id', sa.UUID(), sa.ForeignKey('claims.id'), nullable=False),
        sa.Column('evidence_id', sa.UUID(), sa.ForeignKey('evidence.id'), nullable=False),
        sa.Column('excerpt', sa.Text(), nullable=True),
        sa.Column('relevance_score', sa.Float(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_citations_claim_id', 'citations', ['claim_id'])
    op.create_index('ix_citations_evidence_id', 'citations', ['evidence_id'])
    op.create_index('ix_citations_claim_evidence', 'citations', ['claim_id', 'evidence_id'])


def downgrade() -> None:
    op.drop_index('ix_citations_claim_evidence', table_name='citations')
    op.drop_index('ix_citations_evidence_id', table_name='citations')
    op.drop_index('ix_citations_claim_id', table_name='citations')
    op.drop_table('citations')
    op.drop_index('ix_evidence_run_document', table_name='evidence')
    op.drop_index('ix_evidence_chunk_id', table_name='evidence')
    op.drop_index('ix_evidence_document_id', table_name='evidence')
    op.drop_index('ix_evidence_workflow_run_id', table_name='evidence')
    op.drop_table('evidence')
