"""add_updated_at_to_superdocs_sessions

Revision ID: df5df4d7c7d8
Revises: 0006_phase8_memo_sections
Create Date: 2026-08-19 13:30:14.752834

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'df5df4d7c7d8'
down_revision: Union[str, Sequence[str], None] = '0006_phase8_memo_sections'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
