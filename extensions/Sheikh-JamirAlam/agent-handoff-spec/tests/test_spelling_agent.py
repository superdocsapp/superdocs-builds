from datetime import datetime, timezone

import pytest

from agents import DocumentState, SpellingFixAgent
from schema import ReviewState


def test_spelling_agent_changes_only_target_section_and_issues_next_envelope() -> None:
    document = DocumentState(
        document_id="invoice-2026",
        review_state=ReviewState.DRAFT,
        sections={
            "narrative": "Payment recived within 30 days.",
            "pricing_table": "Subtotal: 100",
        },
    )
    envelope = {
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

    result = SpellingFixAgent().process(
        envelope,
        document,
        {"narrative": {"recived": "received"}},
    )

    assert document.sections["narrative"] == "Payment recived within 30 days."
    assert result.changed_sections["narrative"][1] == "Payment received within 30 days."
    assert document.sections["pricing_table"] == "Subtotal: 100"
    assert result.changed_sections == {
        "narrative": (
            "Payment recived within 30 days.",
            "Payment received within 30 days.",
        )
    }
    assert result.next_envelope.scope.target_sections == ["pricing_table"]
    assert result.next_envelope.issued_by == "spelling-agent"
    assert result.next_envelope.assigned_to == "math-check-agent"


def test_spelling_agent_rejects_mismatched_document() -> None:
    document = DocumentState(
        "other-document", ReviewState.DRAFT, {"narrative": "text"})
    envelope = {
        "document_id": "invoice-2026",
        "assigned_to": "spelling-agent",
        "scope": {"action": "fix spelling", "target_sections": ["narrative"]},
        "review_state": "draft",
        "issued_by": "orchestrator",
        "issued_at": datetime(2026, 8, 24, tzinfo=timezone.utc),
    }

    with pytest.raises(ValueError, match="mismatched document"):
        SpellingFixAgent().process(envelope, document, {})


def test_spelling_agent_rejects_absent_target_section() -> None:
    document = DocumentState(
        "invoice-2026", ReviewState.DRAFT, {"narrative": "text"})
    envelope = {
        "document_id": "invoice-2026",
        "assigned_to": "spelling-agent",
        "scope": {"action": "fix spelling", "target_sections": ["missing"]},
        "review_state": "draft",
        "issued_by": "orchestrator",
        "issued_at": datetime(2026, 8, 24, tzinfo=timezone.utc),
    }

    with pytest.raises(ValueError, match="absent from document"):
        SpellingFixAgent().process(envelope, document, {})


def test_spelling_agent_rejects_forbidden_target_section() -> None:
    document = DocumentState(
        "invoice-2026", ReviewState.DRAFT, {
            "narrative": "text", "pricing_table": "100"}
    )
    envelope = {
        "document_id": "invoice-2026",
        "assigned_to": "spelling-agent",
        "scope": {"action": "correct orthography", "target_sections": ["narrative"]},
        "restrictions": {"forbidden_sections": ["narrative"]},
        "review_state": "draft",
        "issued_by": "orchestrator",
        "issued_at": datetime(2026, 8, 24, tzinfo=timezone.utc),
    }

    with pytest.raises(ValueError, match="overlap"):
        SpellingFixAgent().process(envelope, document, {})
