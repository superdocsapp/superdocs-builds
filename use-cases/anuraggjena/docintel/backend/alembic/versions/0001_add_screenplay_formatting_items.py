"""add screenplay_formatting_items table

Revision ID: b7c8d9e0f1a2
Revises: a1b2c3d4e5f6
Create Date: 2026-08-09 14:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = 'b7c8d9e0f1a2'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'screenplay_formatting_items',
        sa.Column('id', UUID(as_uuid=True), nullable=False),
        sa.Column('workflow_run_id', UUID(as_uuid=True), sa.ForeignKey('workflow_runs.id'), nullable=False),
        sa.Column('review_id', UUID(as_uuid=True), sa.ForeignKey('reviews.id'), nullable=True),
        sa.Column('element_index', sa.Integer(), nullable=False),
        sa.Column('element_type', sa.String(), nullable=False),
        sa.Column('scene_number', sa.Integer(), nullable=True),
        sa.Column('character_name', sa.String(), nullable=True),
        sa.Column('original_text', sa.Text(), nullable=False),
        sa.Column('formatted_text', sa.Text(), nullable=False),
        sa.Column('change_type', sa.String(), nullable=False),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('diff_tokens', sa.JSON(), nullable=True),
        sa.Column('content_drift', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('status', sa.String(), nullable=False, server_default='pending'),
        sa.Column('reviewer_comment', sa.Text(), nullable=True),
        sa.Column('confidence_score', sa.Float(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
    )

    # Single-column indexes
    op.create_index('ix_screenplay_formatting_items_workflow_run_id', 'screenplay_formatting_items', ['workflow_run_id'])
    op.create_index('ix_screenplay_formatting_items_review_id', 'screenplay_formatting_items', ['review_id'])

    # Composite indexes for performance
    op.create_index('ix_screenplay_run_element_idx', 'screenplay_formatting_items', ['workflow_run_id', 'element_index'])
    op.create_index('ix_screenplay_review_status', 'screenplay_formatting_items', ['review_id', 'status'])


def downgrade() -> None:
    op.drop_index('ix_screenplay_review_status', table_name='screenplay_formatting_items')
    op.drop_index('ix_screenplay_run_element_idx', table_name='screenplay_formatting_items')
    op.drop_index('ix_screenplay_formatting_items_review_id', table_name='screenplay_formatting_items')
    op.drop_index('ix_screenplay_formatting_items_workflow_run_id', table_name='screenplay_formatting_items')
    op.drop_table('screenplay_formatting_items')
