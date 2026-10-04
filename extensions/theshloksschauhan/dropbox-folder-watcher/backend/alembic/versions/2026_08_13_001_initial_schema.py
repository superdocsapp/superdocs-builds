"""initial schema

Revision ID: 001
Revises: 
Create Date: 2026-08-13
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import Uuid as UUID

# revision identifiers, used by Alembic.
revision: str = '001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -- clients --
    op.create_table(
        'clients',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('dropbox_folder_root', sa.String(1024), nullable=False),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
    )

    # -- folder_configs --
    op.create_table(
        'folder_configs',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('client_id', UUID(as_uuid=True), sa.ForeignKey('clients.id'), nullable=False),
        sa.Column('dropbox_folder_path', sa.String(1024), nullable=False, unique=True),
        sa.Column('treatment', sa.String(255), nullable=False),
        sa.Column('template_id', sa.String(255), nullable=True),
        sa.Column('instruction_text', sa.Text, nullable=True),
        sa.Column('output_naming_pattern', sa.String(512), nullable=False,
                  server_default='{basename}.superdocs.{treatment}{ext}'),
        sa.Column('allowed_extensions', sa.JSON, nullable=True),
        sa.Column('enabled', sa.Boolean, nullable=False, server_default='true'),
        sa.Column('preview_mode', sa.Boolean, nullable=False, server_default='false'),
        sa.Column('debounce_seconds', sa.Integer, nullable=False, server_default='30'),
        sa.Column('operation_budget_per_hour', sa.Integer, nullable=False, server_default='20'),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index('ix_folder_configs_client_id', 'folder_configs', ['client_id'])

    # -- jobs --
    # Create the enum types first
    jobstatus_enum = sa.Enum(
        'DISCOVERED', 'STABILIZING', 'QUEUED', 'PROCESSING', 'REVIEW_PENDING',
        'APPROVED', 'REJECTED', 'EXPORTING', 'WRITING_BACK', 'COMPLETED', 'FAILED',
        name='jobstatus',
    )

    op.create_table(
        'jobs',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('client_id', UUID(as_uuid=True), sa.ForeignKey('clients.id'), nullable=False),
        sa.Column('folder_config_id', UUID(as_uuid=True), sa.ForeignKey('folder_configs.id'), nullable=False),
        sa.Column('source_path', sa.String(1024), nullable=False),
        sa.Column('source_rev', sa.String(128), nullable=False),
        sa.Column('source_content_hash', sa.String(128), nullable=True),
        sa.Column('status', jobstatus_enum, nullable=False, server_default='DISCOVERED'),
        sa.Column('superdocs_doc_id', sa.String(255), nullable=True),
        sa.Column('preview', sa.Boolean, nullable=False, server_default='false'),
        sa.Column('locked_by', sa.String(255), nullable=True),
        sa.Column('locked_at', sa.DateTime, nullable=True),
        sa.Column('retry_count', sa.Integer, nullable=False, server_default='0'),
        sa.Column('error_message', sa.Text, nullable=True),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime, server_default=sa.func.now()),
        sa.UniqueConstraint('client_id', 'source_rev', name='uq_job_client_rev'),
    )
    op.create_index('ix_jobs_client_id', 'jobs', ['client_id'])
    op.create_index('ix_jobs_status', 'jobs', ['status'])

    # -- dropbox_events --
    op.create_table(
        'dropbox_events',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('dropbox_path', sa.String(1024), nullable=False),
        sa.Column('content_hash', sa.String(128), nullable=True),
        sa.Column('rev', sa.String(128), nullable=True),
        sa.Column('size', sa.BigInteger, nullable=True),
        sa.Column('client_modified', sa.DateTime, nullable=True),
        sa.Column('observed_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('resolved_job_id', UUID(as_uuid=True), sa.ForeignKey('jobs.id'), nullable=True),
    )
    op.create_index('ix_dropbox_events_dropbox_path', 'dropbox_events', ['dropbox_path'])

    # -- superdocs_calls --
    calltype_enum = sa.Enum('UPLOAD', 'CHAT', 'APPROVE', 'EXPORT', name='superdocscalltype')

    op.create_table(
        'superdocs_calls',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('job_id', UUID(as_uuid=True), sa.ForeignKey('jobs.id'), nullable=False),
        sa.Column('call_type', calltype_enum, nullable=False),
        sa.Column('request_summary', sa.Text, nullable=True),
        sa.Column('response_summary', sa.Text, nullable=True),
        sa.Column('success', sa.Boolean, nullable=False),
        sa.Column('error', sa.Text, nullable=True),
        sa.Column('started_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('finished_at', sa.DateTime, nullable=True),
    )
    op.create_index('ix_superdocs_calls_job_id', 'superdocs_calls', ['job_id'])

    # -- known_outputs --
    op.create_table(
        'known_outputs',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('job_id', UUID(as_uuid=True), sa.ForeignKey('jobs.id'), nullable=False),
        sa.Column('output_path', sa.String(1024), nullable=False),
        sa.Column('output_rev', sa.String(128), nullable=True),
        sa.Column('output_content_hash', sa.String(128), nullable=True),
        sa.Column('written_at', sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index('ix_known_outputs_job_id', 'known_outputs', ['job_id'])
    op.create_index('ix_known_outputs_output_path', 'known_outputs', ['output_path'])

    # -- events (state transition audit log) --
    op.create_table(
        'events',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('job_id', UUID(as_uuid=True), sa.ForeignKey('jobs.id'), nullable=False),
        sa.Column('from_state', sa.String(50), nullable=True),
        sa.Column('to_state', sa.String(50), nullable=False),
        sa.Column('actor', sa.String(255), nullable=False),
        sa.Column('detail', sa.Text, nullable=True),
        sa.Column('occurred_at', sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index('ix_events_job_id', 'events', ['job_id'])

    # -- errors --
    op.create_table(
        'errors',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('job_id', UUID(as_uuid=True), sa.ForeignKey('jobs.id'), nullable=False),
        sa.Column('stage', sa.String(50), nullable=False),
        sa.Column('message', sa.Text, nullable=False),
        sa.Column('retryable', sa.Boolean, nullable=False, server_default='true'),
        sa.Column('occurred_at', sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index('ix_errors_job_id', 'errors', ['job_id'])

    # -- operation_metrics --
    op.create_table(
        'operation_metrics',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('job_id', UUID(as_uuid=True), sa.ForeignKey('jobs.id'), nullable=False),
        sa.Column('stage', sa.String(50), nullable=False),
        sa.Column('duration_ms', sa.Integer, nullable=False),
        sa.Column('superdocs_operations_used', sa.Integer, nullable=False, server_default='0'),
        sa.Column('recorded_at', sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index('ix_operation_metrics_job_id', 'operation_metrics', ['job_id'])


def downgrade() -> None:
    op.drop_table('operation_metrics')
    op.drop_table('errors')
    op.drop_table('events')
    op.drop_table('known_outputs')
    op.drop_table('superdocs_calls')
    op.drop_table('dropbox_events')
    op.drop_table('jobs')
    op.drop_table('folder_configs')
    op.drop_table('clients')

    # Drop enum types
    sa.Enum(name='jobstatus').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='superdocscalltype').drop(op.get_bind(), checkfirst=True)
