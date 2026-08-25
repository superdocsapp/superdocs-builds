"""Phase 7: SuperDocs integration

Revision ID: 0005_phase7_superdocs
Revises: 2026_08_10_phase_5c_auth_constraints
Create Date: 2026-08-12

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '0005_phase7_superdocs'
down_revision = 'phase_5c_auth_constraints'
branch_labels = None
depends_on = None


def upgrade():
    """Add SuperDocs integration tables and columns."""

    # Create superdocs_sessions table
    op.create_table(
        'superdocs_sessions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('workflow_run_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('superdocs_session_id', sa.String(256), nullable=False),
        sa.Column('superdocs_document_id', sa.String(256), nullable=True),
        sa.Column('status', sa.String(50), nullable=False, server_default='active'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['workflow_run_id'], ['workflow_runs.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('workflow_run_id', name='uq_superdocs_sessions_run')
    )

    # Create indexes on superdocs_sessions
    op.create_index('idx_superdocs_sessions_run', 'superdocs_sessions', ['workflow_run_id'])
    op.create_index('idx_superdocs_sessions_status', 'superdocs_sessions', ['status'])
    op.create_index('idx_superdocs_sessions_session_id', 'superdocs_sessions', ['superdocs_session_id'])

    # Extend claims table with SuperDocs references
    op.add_column('claims', sa.Column('superdocs_change_id', sa.String(256), nullable=True))
    op.add_column('claims', sa.Column('superdocs_job_id', sa.String(256), nullable=True))

    # Create indexes on claims SuperDocs columns
    op.create_index('idx_claims_superdocs_change', 'claims', ['superdocs_change_id'])
    op.create_index('idx_claims_superdocs_job', 'claims', ['superdocs_job_id'])

    # Extend workflow_runs table for focused updates
    op.add_column('workflow_runs', sa.Column('is_focused_update', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('workflow_runs', sa.Column('baseline_run_id', postgresql.UUID(as_uuid=True), nullable=True))

    # Create index and foreign key for baseline_run_id
    op.create_index('idx_workflow_runs_baseline', 'workflow_runs', ['baseline_run_id'])
    op.create_foreign_key(
        'fk_workflow_runs_baseline',
        'workflow_runs',
        'workflow_runs',
        ['baseline_run_id'],
        ['id'],
        ondelete='SET NULL'
    )

    # Extend workflow_stages table for agentic decisions
    op.add_column('workflow_stages', sa.Column('decision_type', sa.String(50), nullable=True))
    op.add_column('workflow_stages', sa.Column('decision_reason', sa.Text(), nullable=True))
    op.add_column('workflow_stages', sa.Column('decision_metadata', postgresql.JSON(astext_type=sa.Text()), nullable=True))

    # Create index on decision_type
    op.create_index('idx_workflow_stages_decision', 'workflow_stages', ['decision_type'])


def downgrade():
    """Remove SuperDocs integration tables and columns."""

    # Drop workflow_stages columns
    op.drop_index('idx_workflow_stages_decision', table_name='workflow_stages')
    op.drop_column('workflow_stages', 'decision_metadata')
    op.drop_column('workflow_stages', 'decision_reason')
    op.drop_column('workflow_stages', 'decision_type')

    # Drop workflow_runs columns
    op.drop_constraint('fk_workflow_runs_baseline', 'workflow_runs', type_='foreignkey')
    op.drop_index('idx_workflow_runs_baseline', table_name='workflow_runs')
    op.drop_column('workflow_runs', 'baseline_run_id')
    op.drop_column('workflow_runs', 'is_focused_update')

    # Drop claims columns
    op.drop_index('idx_claims_superdocs_job', table_name='claims')
    op.drop_index('idx_claims_superdocs_change', table_name='claims')
    op.drop_column('claims', 'superdocs_job_id')
    op.drop_column('claims', 'superdocs_change_id')

    # Drop superdocs_sessions table
    op.drop_index('idx_superdocs_sessions_session_id', table_name='superdocs_sessions')
    op.drop_index('idx_superdocs_sessions_status', table_name='superdocs_sessions')
    op.drop_index('idx_superdocs_sessions_run', table_name='superdocs_sessions')
    op.drop_table('superdocs_sessions')
