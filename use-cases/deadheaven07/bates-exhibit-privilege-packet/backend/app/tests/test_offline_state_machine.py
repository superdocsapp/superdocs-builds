"""Offline redaction state machine tests.

Proves the core compliance invariant: nothing is modified until a human
approves, and rejected candidates can never be applied.  Entirely offline,
no DB, no network.
"""

import pytest

from app.domain.redaction import RedactionStatus
from app.services.redaction_state import (
    InvalidTransitionError,
    RedactionStateMachine,
)


class TestRedactionStateMachine:
    def test_proposed_to_approved(self):
        assert (
            RedactionStateMachine.transition(RedactionStatus.PROPOSED, RedactionStatus.APPROVED)
            == RedactionStatus.APPROVED
        )

    def test_proposed_to_rejected(self):
        assert (
            RedactionStateMachine.transition(RedactionStatus.PROPOSED, RedactionStatus.REJECTED)
            == RedactionStatus.REJECTED
        )

    def test_approved_to_applied(self):
        assert (
            RedactionStateMachine.transition(RedactionStatus.APPROVED, RedactionStatus.APPLIED)
            == RedactionStatus.APPLIED
        )

    def test_applied_to_verified(self):
        assert (
            RedactionStateMachine.transition(RedactionStatus.APPLIED, RedactionStatus.VERIFIED)
            == RedactionStatus.VERIFIED
        )

    def test_rejected_is_terminal(self):
        assert RedactionStateMachine.is_terminal(RedactionStatus.REJECTED)
        assert RedactionStateMachine.allowed_targets(RedactionStatus.REJECTED) == []

    def test_verified_is_terminal(self):
        assert RedactionStateMachine.is_terminal(RedactionStatus.VERIFIED)
        assert RedactionStateMachine.allowed_targets(RedactionStatus.VERIFIED) == []

    def test_cannot_apply_without_approval(self):
        """PROPOSED -> APPLIED is not allowed."""
        assert not RedactionStateMachine.can_transition(
            RedactionStatus.PROPOSED, RedactionStatus.APPLIED
        )

    def test_cannot_approve_after_rejection(self):
        """REJECTED -> APPROVED is not allowed (terminal)."""
        assert not RedactionStateMachine.can_transition(
            RedactionStatus.REJECTED, RedactionStatus.APPROVED
        )

    def test_cannot_verify_after_rejection(self):
        """REJECTED -> VERIFIED is not allowed (terminal)."""
        assert not RedactionStateMachine.can_transition(
            RedactionStatus.REJECTED, RedactionStatus.VERIFIED
        )

    def test_invalid_transition_raises(self):
        with pytest.raises(InvalidTransitionError):
            RedactionStateMachine.transition(RedactionStatus.PROPOSED, RedactionStatus.APPLIED)

    def test_full_happy_path(self):
        """PROPOSED -> PENDING_APPROVAL -> APPROVED -> APPLIED -> VERIFIED."""
        s = RedactionStatus.PROPOSED
        s = RedactionStateMachine.transition(s, RedactionStatus.PENDING_APPROVAL)
        s = RedactionStateMachine.transition(s, RedactionStatus.APPROVED)
        s = RedactionStateMachine.transition(s, RedactionStatus.APPLIED)
        s = RedactionStateMachine.transition(s, RedactionStatus.VERIFIED)
        assert s == RedactionStatus.VERIFIED
        assert RedactionStateMachine.is_terminal(s)

    def test_proposed_to_pending_approval(self):
        assert (
            RedactionStateMachine.transition(
                RedactionStatus.PROPOSED, RedactionStatus.PENDING_APPROVAL
            )
            == RedactionStatus.PENDING_APPROVAL
        )

    def test_pending_approval_to_rejected(self):
        assert (
            RedactionStateMachine.transition(
                RedactionStatus.PENDING_APPROVAL, RedactionStatus.REJECTED
            )
            == RedactionStatus.REJECTED
        )

    def test_failed_can_retry_to_proposed(self):
        """FAILED -> PROPOSED is allowed (retry)."""
        assert (
            RedactionStateMachine.transition(RedactionStatus.FAILED, RedactionStatus.PROPOSED)
            == RedactionStatus.PROPOSED
        )
