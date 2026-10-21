"""Phase 5c: Enforce authentication constraints

Revision ID: phase_5c_auth_constraints
Revises: phase_5a_auth
Create Date: 2026-08-10

This is Phase 5c of the 3-phase migration strategy:
- Phase 5a: Added users/refresh_tokens tables (DONE)
- Phase 5b: Migrated existing owner_id data (MANUAL SCRIPT - must be run first)
- Phase 5c (THIS FILE): Enforce constraints

[WARNING]  PREREQUISITES:
1. Phase 5a migration must be run: alembic upgrade phase_5a_auth
2. Seed admin must be created: python -m alembic.scripts.create_seed_admin
3. Workspace owners must be migrated: python -m alembic.scripts.migrate_workspace_owners
4. All workspaces MUST have valid owner_user_id (verify before running)

This migration will FAIL if any workspace has NULL owner_user_id.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = 'phase_5c_auth_constraints'
down_revision = 'phase_5a_auth'
branch_labels = None
depends_on = None


def upgrade():
    print("=" * 80)
    print("Phase 5c: Enforcing Authentication Constraints")
    print("=" * 80)
    print()

    # SAFETY CHECK: Verify all workspaces have owner_user_id
    print("[WARNING]  Verifying data integrity...")
    conn = op.get_bind()
    result = conn.execute(
        sa.text("SELECT COUNT(*) FROM workspaces WHERE owner_user_id IS NULL")
    )
    null_count = result.scalar()

    if null_count > 0:
        print()
        print("=" * 80)
        print(f"[ERROR] MIGRATION BLOCKED: {null_count} workspaces have NULL owner_user_id")
        print("=" * 80)
        print()
        print("You MUST run the data migration script first:")
        print("  python -m alembic.scripts.migrate_workspace_owners")
        print()
        print("To see which workspaces are affected:")
        print("  SELECT id, name, owner_id FROM workspaces WHERE owner_user_id IS NULL;")
        print()
        print("=" * 80)
        raise Exception(f"{null_count} workspaces have NULL owner_user_id - data migration required")

    print("[OK] All workspaces have valid owner_user_id")
    print()

    # Add foreign key constraint
    print("Adding foreign key: workspaces.owner_user_id -> users.id...")
    op.create_foreign_key(
        'fk_workspaces_owner_user_id',
        'workspaces',
        'users',
        ['owner_user_id'],
        ['id'],
        ondelete='RESTRICT'  # Prevent deleting users who own workspaces
    )
    print("[OK] Foreign key constraint added")
    print()

    # Make owner_user_id NOT NULL
    print("Making owner_user_id NOT NULL...")
    op.alter_column(
        'workspaces',
        'owner_user_id',
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False
    )
    print("[OK] NOT NULL constraint added")
    print()

    # Drop old owner_id column (string-based, no longer needed)
    print("Dropping old owner_id column...")
    op.drop_column('workspaces', 'owner_id')
    print("[OK] Old owner_id column dropped")
    print()

    print("=" * 80)
    print("[OK] PHASE 5C MIGRATION COMPLETE")
    print("=" * 80)
    print()
    print("Authentication system is now fully active:")
    print("  • All workspaces linked to user accounts")
    print("  • Foreign key constraints enforced")
    print("  • Old string-based owner_id removed")
    print()
    print("[WARNING]  BREAKING CHANGES:")
    print("  • API endpoints now require authentication")
    print("  • owner_id cannot be specified in requests (derived from JWT)")
    print("  • Frontend must be updated to handle authentication")
    print()
    print("Next steps:")
    print("  1. Test authentication endpoints:")
    print("     POST /api/v1/auth/login")
    print("     GET /api/v1/auth/me")
    print()
    print("  2. Update frontend to use authentication")
    print("  3. Run regression tests:")
    print("     pytest tests/")
    print()
    print("=" * 80)


def downgrade():
    print("=" * 80)
    print("ROLLING BACK Phase 5c")
    print("=" * 80)
    print()

    # Re-add owner_id column
    print("Re-adding owner_id column...")
    op.add_column('workspaces', sa.Column('owner_id', sa.String(), nullable=True))

    # Copy owner_user_id back to owner_id (as string)
    print("Copying owner_user_id -> owner_id...")
    conn = op.get_bind()
    conn.execute(
        sa.text("UPDATE workspaces SET owner_id = CAST(owner_user_id AS TEXT)")
    )

    # Make owner_id NOT NULL
    op.alter_column('workspaces', 'owner_id', nullable=False)
    print("[OK] owner_id column restored")
    print()

    # Make owner_user_id nullable again
    print("Making owner_user_id nullable...")
    op.alter_column(
        'workspaces',
        'owner_user_id',
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=True
    )
    print("[OK] owner_user_id made nullable")
    print()

    # Drop foreign key constraint
    print("Dropping foreign key constraint...")
    op.drop_constraint('fk_workspaces_owner_user_id', 'workspaces', type_='foreignkey')
    print("[OK] Foreign key constraint dropped")
    print()

    print("=" * 80)
    print("Phase 5c rollback complete")
    print("System reverted to Phase 5a state")
    print("=" * 80)
