"""add reviews claims exports quality gate audit knowledge tables

Revision ID: 50f1fb7be338
Revises: d9dfea6952db
Create Date: 2026-08-08 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '50f1fb7be338'
down_revision: Union[str, Sequence[str], None] = 'd9dfea6952db'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # reviews table
    op.create_table(
        'reviews',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('workflow_run_id', sa.UUID(), sa.ForeignKey('workflow_runs.id'), nullable=False),
        sa.Column('workspace_id', sa.UUID(), sa.ForeignKey('workspaces.id'), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('reviewer_id', sa.String(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_reviews_workflow_run_id', 'reviews', ['workflow_run_id'])
    op.create_index('ix_reviews_workspace_id', 'reviews', ['workspace_id'])
    op.create_index('ix_reviews_workspace_status', 'reviews', ['workspace_id', 'status'])

    # claims table
    op.create_table(
        'claims',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('workflow_run_id', sa.UUID(), sa.ForeignKey('workflow_runs.id'), nullable=False),
        sa.Column('review_id', sa.UUID(), sa.ForeignKey('reviews.id'), nullable=True),
        sa.Column('claim_type', sa.String(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('original_content', sa.Text(), nullable=True),
        sa.Column('edited_by', sa.String(), nullable=True),
        sa.Column('source_stage', sa.String(), nullable=True),
        sa.Column('confidence_score', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_claims_workflow_run_id', 'claims', ['workflow_run_id'])
    op.create_index('ix_claims_review_id', 'claims', ['review_id'])
    op.create_index('ix_claims_workflow_run_status', 'claims', ['workflow_run_id', 'status'])

    # exports table
    op.create_table(
        'exports',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('workspace_id', sa.UUID(), sa.ForeignKey('workspaces.id'), nullable=False),
        sa.Column('workflow_run_id', sa.UUID(), sa.ForeignKey('workflow_runs.id'), nullable=True),
        sa.Column('review_id', sa.UUID(), sa.ForeignKey('reviews.id'), nullable=True),
        sa.Column('filename', sa.String(), nullable=False),
        sa.Column('format', sa.String(), nullable=False),
        sa.Column('storage_path', sa.String(), nullable=False),
        sa.Column('file_size', sa.Integer(), nullable=False),
        sa.Column('exported_by', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_exports_workspace_id', 'exports', ['workspace_id'])
    op.create_index('ix_exports_workflow_run_id', 'exports', ['workflow_run_id'])
    op.create_index('ix_exports_review_id', 'exports', ['review_id'])
    op.create_index('ix_exports_workspace_created', 'exports', ['workspace_id', 'created_at'])

    # audit_logs table
    op.create_table(
        'audit_logs',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('workspace_id', sa.UUID(), sa.ForeignKey('workspaces.id'), nullable=True),
        sa.Column('event_type', sa.String(), nullable=False),
        sa.Column('actor_id', sa.String(), nullable=True),
        sa.Column('resource_type', sa.String(), nullable=True),
        sa.Column('resource_id', sa.String(), nullable=True),
        sa.Column('details', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_audit_logs_workspace_id', 'audit_logs', ['workspace_id'])
    op.create_index('ix_audit_logs_event_type', 'audit_logs', ['event_type'])
    op.create_index('ix_audit_workspace_event', 'audit_logs', ['workspace_id', 'event_type'])
    op.create_index('ix_audit_resource', 'audit_logs', ['resource_type', 'resource_id'])

    # quality_gate_configs table
    op.create_table(
        'quality_gate_configs',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('workspace_id', sa.UUID(), sa.ForeignKey('workspaces.id'), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('block_on_failure', sa.Boolean(), nullable=False),
        sa.Column('checks_config', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('workspace_id'),
    )

    # quality_gate_results table
    op.create_table(
        'quality_gate_results',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('workflow_run_id', sa.UUID(), sa.ForeignKey('workflow_runs.id'), nullable=False),
        sa.Column('config_id', sa.UUID(), sa.ForeignKey('quality_gate_configs.id'), nullable=True),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('checks_run', sa.Integer(), nullable=False),
        sa.Column('checks_passed', sa.Integer(), nullable=False),
        sa.Column('checks_failed', sa.Integer(), nullable=False),
        sa.Column('blocking', sa.Boolean(), nullable=False),
        sa.Column('details', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_qg_results_run', 'quality_gate_results', ['workflow_run_id'])

    # knowledge_entries table
    op.create_table(
        'knowledge_entries',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('workspace_id', sa.UUID(), sa.ForeignKey('workspaces.id'), nullable=False),
        sa.Column('workflow_type', sa.String(), nullable=False),
        sa.Column('source_run_id', sa.UUID(), sa.ForeignKey('workflow_runs.id'), nullable=True),
        sa.Column('source_document_id', sa.UUID(), sa.ForeignKey('documents.id'), nullable=True),
        sa.Column('entry_type', sa.String(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('extra_metadata', sa.JSON(), nullable=False),
        sa.Column('confidence_score', sa.Float(), nullable=True),
        sa.Column('tags', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_knowledge_entries_workspace_id', 'knowledge_entries', ['workspace_id'])
    op.create_index('ix_knowledge_entries_workflow_type', 'knowledge_entries', ['workflow_type'])
    op.create_index('ix_knowledge_workspace_type', 'knowledge_entries', ['workspace_id', 'workflow_type'])


def downgrade() -> None:
    op.drop_index('ix_knowledge_workspace_type', table_name='knowledge_entries')
    op.drop_index('ix_knowledge_entries_workflow_type', table_name='knowledge_entries')
    op.drop_index('ix_knowledge_entries_workspace_id', table_name='knowledge_entries')
    op.drop_table('knowledge_entries')
    op.drop_index('ix_qg_results_run', table_name='quality_gate_results')
    op.drop_table('quality_gate_results')
    op.drop_table('quality_gate_configs')
    op.drop_index('ix_audit_resource', table_name='audit_logs')
    op.drop_index('ix_audit_workspace_event', table_name='audit_logs')
    op.drop_index('ix_audit_logs_event_type', table_name='audit_logs')
    op.drop_index('ix_audit_logs_workspace_id', table_name='audit_logs')
    op.drop_table('audit_logs')
    op.drop_index('ix_exports_workspace_created', table_name='exports')
    op.drop_index('ix_exports_review_id', table_name='exports')
    op.drop_index('ix_exports_workflow_run_id', table_name='exports')
    op.drop_index('ix_exports_workspace_id', table_name='exports')
    op.drop_table('exports')
    op.drop_index('ix_claims_workflow_run_status', table_name='claims')
    op.drop_index('ix_claims_review_id', table_name='claims')
    op.drop_index('ix_claims_workflow_run_id', table_name='claims')
    op.drop_table('claims')
    op.drop_index('ix_reviews_workspace_status', table_name='reviews')
    op.drop_index('ix_reviews_workspace_id', table_name='reviews')
    op.drop_index('ix_reviews_workflow_run_id', table_name='reviews')
    op.drop_table('reviews')
