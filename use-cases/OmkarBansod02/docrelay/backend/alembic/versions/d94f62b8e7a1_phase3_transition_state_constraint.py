"""allow the Phase 3 reviewed-export terminal state in transition evidence

Revision ID: d94f62b8e7a1
Revises: c6a8d31f4b2e
Create Date: 2026-08-10
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d94f62b8e7a1"
down_revision: str | None = "c6a8d31f4b2e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PHASE3_STATES = (
    "QUEUED",
    "BASELINING",
    "EDITING",
    "AWAITING_REVIEW",
    "REVIEWED_EXPORT_READY",
    "READY_TO_COMMIT",
    "PREVIEW_READY",
    "COMMITTING",
    "VERIFYING",
    "SUCCEEDED",
    "CONFLICT",
    "UNSUPPORTED",
    "SKIPPED",
    "EXPIRED",
    "COMMIT_OUTCOME_UNKNOWN",
    "VERIFICATION_FAILED",
    "FAILED",
    "CANCELLED",
)

_PRE_PHASE3_STATES = tuple(value for value in _PHASE3_STATES if value != "REVIEWED_EXPORT_READY")


def _in_constraint(column: str, values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({quoted})"


def upgrade() -> None:
    op.drop_constraint(
        op.f("ck_run_transitions_sync_run_from_state"), "run_transitions", type_="check"
    )
    op.drop_constraint(
        op.f("ck_run_transitions_sync_run_to_state"), "run_transitions", type_="check"
    )
    op.create_check_constraint(
        "sync_run_from_state",
        "run_transitions",
        _in_constraint("from_state", _PHASE3_STATES),
    )
    op.create_check_constraint(
        "sync_run_to_state",
        "run_transitions",
        _in_constraint("to_state", _PHASE3_STATES),
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_run_transitions_sync_run_from_state"), "run_transitions", type_="check"
    )
    op.drop_constraint(
        op.f("ck_run_transitions_sync_run_to_state"), "run_transitions", type_="check"
    )
    op.create_check_constraint(
        "sync_run_from_state",
        "run_transitions",
        _in_constraint("from_state", _PRE_PHASE3_STATES),
    )
    op.create_check_constraint(
        "sync_run_to_state",
        "run_transitions",
        _in_constraint("to_state", _PRE_PHASE3_STATES),
    )
