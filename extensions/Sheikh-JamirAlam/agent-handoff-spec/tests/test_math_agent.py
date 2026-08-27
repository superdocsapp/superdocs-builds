from datetime import datetime, timezone
from decimal import Decimal

import pytest

from agents import DocumentState, MathCheckAgent
from schema import ReviewState


def test_math_agent_corrects_only_wrong_pricing_total() -> None:
    document = DocumentState(
        "invoice-2026",
        ReviewState.PENDING_REVIEW,
        {
            "narrative": "Payment received.",
            "pricing_table": "Widget: 2 x 25 = 50\nService: 3 x 20 = 60\nTotal: 100",
        },
    )
    envelope = {
        "document_id": "invoice-2026",
        "assigned_to": "math-check-agent",
        "scope": {"action": "verify totals", "target_sections": ["pricing_table"]},
        "restrictions": {"forbidden_sections": ["narrative"]},
        "review_state": "pending_review",
        "issued_by": "spelling-agent",
        "issued_at": datetime(2026, 8, 24, tzinfo=timezone.utc),
    }

    result = MathCheckAgent().process(envelope, document)

    assert result.calculated_total == Decimal("110")
    assert document.sections["pricing_table"].endswith("Total: 100")
    assert result.changed_sections["pricing_table"][1].endswith("Total: 110")
    assert document.sections["narrative"] == "Payment received."
    assert result.next_envelope.review_state is ReviewState.PENDING_REVIEW
    assert result.next_envelope.assigned_to == "spelling-agent"


def test_math_agent_corrects_wrong_row_amount_even_when_grand_total_matches() -> None:
    document = DocumentState(
        "invoice-2026", ReviewState.PENDING_REVIEW,
        {"pricing_table": "Widget: 2 x 25 = 999\nService: 3 x 20 = 60\nTotal: 110"},
    )
    envelope = {
        "document_id": "invoice-2026",
        "assigned_to": "math-check-agent",
        "scope": {"action": "verify totals", "target_sections": ["pricing_table"]},
        "review_state": "pending_review",
        "issued_by": "spelling-agent",
        "issued_at": datetime(2026, 8, 24, tzinfo=timezone.utc),
    }

    result = MathCheckAgent().process(envelope, document)

    assert document.sections["pricing_table"] == (
        "Widget: 2 x 25 = 999\nService: 3 x 20 = 60\nTotal: 110"
    )
    assert result.changed_sections["pricing_table"][1] == (
        "Widget: 2 x 25 = 50\nService: 3 x 20 = 60\nTotal: 110"
    )


def test_math_agent_corrects_row_and_total_when_row_correction_changes_length() -> None:
    document = DocumentState(
        "invoice-2026", ReviewState.PENDING_REVIEW,
        {"pricing_table": "Widget: 2 x 25 = 999\nService: 3 x 20 = 60\nTotal: 999"},
    )
    envelope = {
        "document_id": "invoice-2026",
        "assigned_to": "math-check-agent",
        "scope": {"action": "verify totals", "target_sections": ["pricing_table"]},
        "review_state": "pending_review",
        "issued_by": "spelling-agent",
        "issued_at": datetime(2026, 8, 24, tzinfo=timezone.utc),
    }

    result = MathCheckAgent().process(envelope, document)

    assert document.sections["pricing_table"] == (
        "Widget: 2 x 25 = 999\nService: 3 x 20 = 60\nTotal: 999"
    )
    assert result.changed_sections["pricing_table"][1] == (
        "Widget: 2 x 25 = 50\nService: 3 x 20 = 60\nTotal: 110"
    )


def test_math_agent_rejects_wrong_document_state() -> None:
    document = DocumentState(
        "invoice-2026", ReviewState.DRAFT, {"pricing_table": "1 x 10 = 10\nTotal: 10"})
    envelope = {
        "document_id": "invoice-2026",
        "assigned_to": "math-check-agent",
        "scope": {"action": "verify totals", "target_sections": ["pricing_table"]},
        "review_state": "pending_review",
        "issued_by": "spelling-agent",
        "issued_at": datetime(2026, 8, 24, tzinfo=timezone.utc),
    }

    with pytest.raises(ValueError, match="review state"):
        MathCheckAgent().process(envelope, document)


def test_math_agent_rejects_out_of_scope_target() -> None:
    document = DocumentState(
        "invoice-2026", ReviewState.PENDING_REVIEW, {"narrative": "text"})
    envelope = {
        "document_id": "invoice-2026",
        "assigned_to": "math-check-agent",
        "scope": {"action": "verify totals", "target_sections": ["narrative"]},
        "review_state": "pending_review",
        "issued_by": "spelling-agent",
        "issued_at": datetime(2026, 8, 24, tzinfo=timezone.utc),
    }

    with pytest.raises(ValueError, match="pricing_table as its only target"):
        MathCheckAgent().process(envelope, document)


@pytest.mark.parametrize("section_text, message", [
    ("Total: 10", "no parseable line items"),
    ("1 x 10 = 10", "no Total value"),
])
def test_math_agent_rejects_unparseable_pricing_table(section_text: str, message: str) -> None:
    document = DocumentState(
        "invoice-2026", ReviewState.PENDING_REVIEW, {"pricing_table": section_text})
    envelope = {
        "document_id": "invoice-2026",
        "assigned_to": "math-check-agent",
        "scope": {"action": "verify totals", "target_sections": ["pricing_table"]},
        "review_state": "pending_review",
        "issued_by": "spelling-agent",
        "issued_at": datetime(2026, 8, 24, tzinfo=timezone.utc),
    }

    with pytest.raises(ValueError, match=message):
        MathCheckAgent().process(envelope, document)
