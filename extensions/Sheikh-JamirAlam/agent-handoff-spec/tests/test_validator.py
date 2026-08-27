from datetime import datetime, timezone

from schema import ReviewState
from validator import ActionDiff, validate_action


def envelope() -> dict:
    return {
        "document_id": "invoice-2026",
        "assigned_to": "spelling-agent",
        "scope": {"action": "fix spelling", "target_sections": ["narrative"]},
        "restrictions": {
            "forbidden_sections": ["pricing_table"],
            "forbidden_actions": ["verify totals"],
        },
        "review_state": "draft",
        "issued_by": "orchestrator",
        "issued_at": datetime(2026, 8, 24, tzinfo=timezone.utc),
    }


def test_validator_accepts_scoped_action() -> None:
    result = validate_action(
        envelope(), ActionDiff("invoice-2026", "spelling-agent",
                               "spelling-agent", "fix spelling", frozenset({"narrative"}))
    )

    assert result.accepted is True


def test_validator_rejects_real_out_of_scope_action() -> None:
    result = validate_action(
        envelope(), ActionDiff("invoice-2026", "spelling-agent",
                               "spelling-agent", "fix spelling", frozenset({"pricing_table"}))
    )

    assert result.accepted is False
    assert "outside scope" in result.reason


def test_validator_rejects_forbidden_action() -> None:
    result = validate_action(
        envelope(), ActionDiff("invoice-2026", "math-check-agent",
                               "spelling-agent", "verify totals", frozenset({"narrative"}))
    )

    assert result.accepted is False
    assert "forbidden" in result.reason


def test_validator_rejects_mutation_after_approval() -> None:
    approved = envelope() | {"review_state": ReviewState.APPROVED.value}

    result = validate_action(
        approved, ActionDiff("invoice-2026", "spelling-agent",
                             "spelling-agent", "fix spelling", frozenset({"narrative"}))
    )

    assert result.accepted is False
    assert "does not permit mutation" in result.reason


def test_validator_rejects_mismatched_document_id() -> None:
    result = validate_action(
        envelope(), ActionDiff("wrong-document", "spelling-agent",
                               "spelling-agent", "fix spelling", frozenset({"narrative"}))
    )

    assert result.accepted is False
    assert "document_id does not match" in result.reason


def test_validator_rejects_mutation_after_rejection() -> None:
    rejected = envelope() | {"review_state": ReviewState.REJECTED.value}

    result = validate_action(
        rejected, ActionDiff("invoice-2026", "spelling-agent",
                             "spelling-agent", "fix spelling", frozenset({"narrative"}))
    )

    assert result.accepted is False
    assert "does not permit mutation" in result.reason


def test_validator_accepts_action_in_pending_review_state() -> None:
    pending = envelope() | {"review_state": ReviewState.PENDING_REVIEW.value}

    result = validate_action(
        pending, ActionDiff("invoice-2026", "spelling-agent",
                            "spelling-agent", "fix spelling", frozenset({"narrative"}))
    )

    assert result.accepted is True


def test_validator_rejects_invalid_raw_envelope() -> None:
    bad_envelope = envelope() | {"envelope_version": "2.0"}

    result = validate_action(
        bad_envelope, ActionDiff("invoice-2026", "spelling-agent",
                                 "spelling-agent", "fix spelling", frozenset({"narrative"}))
    )

    assert result.accepted is False
    assert "invalid envelope" in result.reason


def test_validator_accepts_genuine_no_op_action() -> None:
    result = validate_action(
        envelope(), ActionDiff("invoice-2026", "spelling-agent",
                               "spelling-agent", "fix spelling", frozenset())
    )

    assert result.accepted is True
