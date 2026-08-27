from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from schema import HandoffEnvelope, validate_envelope


def envelope_data() -> dict:
    return {
        "envelope_version": "1.0",
        "document_id": "invoice-2026",
        "assigned_to": "spelling-agent",
        "scope": {
            "action": "correct spelling",
            "target_sections": ["narrative"],
        },
        "restrictions": {
            "forbidden_sections": ["pricing_table"],
            "forbidden_actions": ["recalculate totals"],
        },
        "review_state": "draft",
        "issued_by": "orchestrator",
        "issued_at": datetime(2026, 8, 24, tzinfo=timezone.utc),
    }


def test_valid_envelope() -> None:
    envelope = validate_envelope(envelope_data())

    assert envelope.document_id == "invoice-2026"
    assert envelope.review_state.value == "draft"


def test_unknown_fields_are_rejected() -> None:
    data = envelope_data()
    data["document_content"] = "secret or raw document text"

    with pytest.raises(ValidationError):
        HandoffEnvelope.model_validate(data)


def test_issued_at_requires_timezone() -> None:
    data = envelope_data()
    data["issued_at"] = datetime(2026, 8, 24)

    with pytest.raises(ValidationError, match="explicit UTC offset"):
        HandoffEnvelope.model_validate(data)


def test_unknown_version_is_rejected() -> None:
    data = envelope_data()
    data["envelope_version"] = "2.0"

    with pytest.raises(ValidationError):
        HandoffEnvelope.model_validate(data)


def test_overlapping_target_and_forbidden_sections_are_rejected() -> None:
    data = envelope_data()
    data["restrictions"]["forbidden_sections"] = ["narrative"]

    with pytest.raises(ValidationError, match="overlap: narrative"):
        HandoffEnvelope.model_validate(data)
