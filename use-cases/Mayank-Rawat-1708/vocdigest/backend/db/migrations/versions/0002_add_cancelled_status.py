"""Add CANCELLED to run_status.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-14

Operators need a way to stop a run that is consuming a shared provider token allowance.
CANCELLED is distinct from FAILED (nothing went wrong) and from PAUSED (a paused run is
expected to resume; a cancelled one is not).
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE cannot run inside a transaction block on older Postgres,
    # and is not reversible, which is why the downgrade below is a no-op.
    op.execute("ALTER TYPE run_status ADD VALUE IF NOT EXISTS 'CANCELLED'")


def downgrade() -> None:
    # Postgres has no DROP VALUE for an enum. Removing it would mean recreating the type
    # and rewriting every dependent column — not worth it for an additive change, and the
    # value is harmless if unused.
    pass