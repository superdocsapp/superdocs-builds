from itertools import pairwise

import pytest

from docrelay.domain.enums import SyncRunState
from docrelay.domain.state_machine import (
    IllegalStateTransition,
    allowed_targets,
    is_terminal,
    require_transition,
)

HAPPY_PATH = (
    SyncRunState.QUEUED,
    SyncRunState.BASELINING,
    SyncRunState.EDITING,
    SyncRunState.AWAITING_REVIEW,
    SyncRunState.EDITING,
    SyncRunState.AWAITING_REVIEW,
    SyncRunState.EDITING,
    SyncRunState.REVIEWED_EXPORT_READY,
    SyncRunState.READY_TO_COMMIT,
    SyncRunState.COMMITTING,
    SyncRunState.VERIFYING,
    SyncRunState.SUCCEEDED,
)


def test_happy_path_and_repeated_review_rounds_are_allowed() -> None:
    transitions = [require_transition(source, target) for source, target in pairwise(HAPPY_PATH)]
    assert transitions[-1].to_state is SyncRunState.SUCCEEDED


def test_preview_is_resumable_to_commit_but_not_success() -> None:
    require_transition(SyncRunState.READY_TO_COMMIT, SyncRunState.PREVIEW_READY)
    require_transition(SyncRunState.PREVIEW_READY, SyncRunState.COMMITTING)
    assert not is_terminal(SyncRunState.PREVIEW_READY)
    assert SyncRunState.SUCCEEDED not in allowed_targets(SyncRunState.PREVIEW_READY)


@pytest.mark.parametrize(
    ("source", "target"),
    [
        (SyncRunState.QUEUED, SyncRunState.SUCCEEDED),
        (SyncRunState.AWAITING_REVIEW, SyncRunState.COMMITTING),
        (SyncRunState.COMMITTING, SyncRunState.CANCELLED),
        (SyncRunState.VERIFYING, SyncRunState.FAILED),
        (SyncRunState.SUCCEEDED, SyncRunState.QUEUED),
        (SyncRunState.CONFLICT, SyncRunState.BASELINING),
    ],
)
def test_illegal_transitions_fail_explicitly(source: SyncRunState, target: SyncRunState) -> None:
    with pytest.raises(IllegalStateTransition, match="illegal SyncRun transition"):
        require_transition(source, target)


def test_attention_and_failure_outcomes_are_terminal_for_the_run() -> None:
    for state in (
        SyncRunState.CONFLICT,
        SyncRunState.UNSUPPORTED,
        SyncRunState.EXPIRED,
        SyncRunState.COMMIT_OUTCOME_UNKNOWN,
        SyncRunState.VERIFICATION_FAILED,
        SyncRunState.FAILED,
        SyncRunState.CANCELLED,
    ):
        assert is_terminal(state)
        assert not allowed_targets(state)
