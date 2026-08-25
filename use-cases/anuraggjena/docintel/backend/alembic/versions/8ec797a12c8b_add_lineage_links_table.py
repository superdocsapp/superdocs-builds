"""add lineage links table

Revision ID: 8ec797a12c8b
Revises: b7c8d9e0f1a2
Create Date: 2026-08-09 22:01:47.320552

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8ec797a12c8b'
down_revision: Union[str, Sequence[str], None] = 'b7c8d9e0f1a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'lineage_links',
        sa.Column('id', sa.UUID(), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('source_type', sa.String(), nullable=False),
        sa.Column('source_id', sa.UUID(), nullable=False),
        sa.Column('target_type', sa.String(), nullable=False),
        sa.Column('target_id', sa.UUID(), nullable=False),
        sa.Column('link_type', sa.String(), nullable=False),
        sa.Column('workflow_run_id', sa.UUID(), nullable=False),
        sa.Column('stage_name', sa.String(), nullable=True),
        sa.Column('metadata', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['workflow_run_id'], ['workflow_runs.id'], name='fk_lineage_links_workflow_run_id'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('source_type', 'source_id', 'target_type', 'target_id', 'link_type', name='uq_lineage_link')
    )

    op.create_index('ix_lineage_links_source', 'lineage_links', ['source_type', 'source_id'])
    op.create_index('ix_lineage_links_target', 'lineage_links', ['target_type', 'target_id'])
    op.create_index('ix_lineage_links_run', 'lineage_links', ['workflow_run_id'])
    op.create_index('ix_lineage_links_type', 'lineage_links', ['link_type'])
    op.create_index('ix_lineage_links_run_type', 'lineage_links', ['workflow_run_id', 'link_type'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_lineage_links_run_type', table_name='lineage_links')
    op.drop_index('ix_lineage_links_type', table_name='lineage_links')
    op.drop_index('ix_lineage_links_run', table_name='lineage_links')
    op.drop_index('ix_lineage_links_target', table_name='lineage_links')
    op.drop_index('ix_lineage_links_source', table_name='lineage_links')
    op.drop_table('lineage_links')
