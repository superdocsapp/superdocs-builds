"""Enforce Phase 4 proof and plan immutability for updates and deletes.

Revision ID: e5b4a9c2d7f0
Revises: d94f62b8e7a1
Create Date: 2026-08-10
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e5b4a9c2d7f0"
down_revision: str | Sequence[str] | None = "d94f62b8e7a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("mapping_proofs", "write_plans", "write_plan_lineage")


def upgrade() -> None:
    for table_name in _TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table_name}_immutable ON {table_name}")
        op.execute(
            f"CREATE TRIGGER trg_{table_name}_immutable "
            f"BEFORE UPDATE OR DELETE ON {table_name} FOR EACH ROW "
            "EXECUTE FUNCTION docrelay_reject_immutable_update()"
        )


def downgrade() -> None:
    for table_name in _TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table_name}_immutable ON {table_name}")
        op.execute(
            f"CREATE TRIGGER trg_{table_name}_immutable "
            f"BEFORE UPDATE ON {table_name} FOR EACH ROW "
            "EXECUTE FUNCTION docrelay_reject_immutable_update()"
        )
