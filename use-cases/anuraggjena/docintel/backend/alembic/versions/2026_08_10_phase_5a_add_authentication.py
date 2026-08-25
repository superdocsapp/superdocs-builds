"""Phase 5a: Add authentication (users, refresh_tokens) - ADDITIVE ONLY

Revision ID: phase_5a_auth
Revises: 8ec797a12c8b
Create Date: 2026-08-10

This is Phase 5a of a 3-phase migration strategy:
- Phase 5a (THIS FILE): Add users and refresh_tokens tables (SAFE, non-breaking)
- Phase 5b (MANUAL SCRIPT): Migrate existing owner_id data to user references
- Phase 5c (SEPARATE MIGRATION): Enforce constraints after data migration

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = 'phase_5a_auth'
down_revision = '8ec797a12c8b'
branch_labels = None
depends_on = None


def upgrade():
    # Create users table
    op.create_table(
        'users',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('email', sa.String(length=254), nullable=False),
        sa.Column('password_hash', sa.String(length=60), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('role', sa.String(length=20), nullable=False, server_default='user'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('force_password_change', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email'),
        sa.CheckConstraint("role IN ('user', 'reviewer', 'admin')", name='valid_role_check')
    )
    op.create_index('ix_users_email', 'users', ['email'])

    # Create refresh_tokens table
    op.create_table(
        'refresh_tokens',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('token_hash', sa.String(length=255), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('is_revoked', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('token_hash')
    )
    op.create_index('ix_refresh_tokens_token_hash', 'refresh_tokens', ['token_hash'])

    # Add owner_user_id column to workspaces (NULLABLE for now - Phase 5c will make NOT NULL)
    op.add_column('workspaces', sa.Column('owner_user_id', postgresql.UUID(as_uuid=True), nullable=True))

    # Add index for performance (will be FK in Phase 5c)
    op.create_index('ix_workspaces_owner_user_id', 'workspaces', ['owner_user_id'])

    print("=" * 80)
    print("Phase 5a Migration Complete")
    print("=" * 80)
    print()
    print("[OK] Created 'users' table")
    print("[OK] Created 'refresh_tokens' table")
    print("[OK] Added 'owner_user_id' column to 'workspaces' (nullable)")
    print()
    print("[NEXT] NEXT STEPS:")
    print("   1. Create seed admin user:")
    print("      python -m alembic.scripts.create_seed_admin")
    print()
    print("   2. Map existing workspace owners to users:")
    print("      python -m alembic.scripts.migrate_workspace_owners")
    print()
    print("   3. Run Phase 5c migration to enforce constraints:")
    print("      alembic upgrade phase_5c_auth_constraints")
    print()
    print("=" * 80)


def downgrade():
    # Drop index
    op.drop_index('ix_workspaces_owner_user_id', table_name='workspaces')

    # Drop new column
    op.drop_column('workspaces', 'owner_user_id')

    # Drop refresh_tokens table
    op.drop_index('ix_refresh_tokens_token_hash', table_name='refresh_tokens')
    op.drop_table('refresh_tokens')

    # Drop users table
    op.drop_index('ix_users_email', table_name='users')
    op.drop_table('users')

    print("Phase 5a migration rolled back")
