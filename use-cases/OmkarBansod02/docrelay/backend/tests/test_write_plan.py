from collections.abc import Callable

import pytest
from pydantic import ValidationError

from docrelay.domain.write_plan import (
    GoogleDocsBatchUpdate,
    SealedWritePlan,
    WritePlanIntegrityError,
)


def test_sealed_plan_is_frozen_and_integrity_verified(
    write_plan_factory: Callable[..., SealedWritePlan],
) -> None:
    plan = write_plan_factory()
    assert plan.verify_integrity()

    with pytest.raises(ValidationError, match="frozen"):
        plan.integrity_sha256 = "f" * 64  # type: ignore[misc]


def test_canonical_hash_is_deterministic(
    write_plan_factory: Callable[..., SealedWritePlan],
) -> None:
    plan = write_plan_factory()
    loaded = SealedWritePlan.model_validate(plan.model_dump(mode="json"))
    assert loaded == plan
    assert loaded.integrity_sha256 == plan.integrity_sha256


def test_tampering_is_detected_on_load(
    write_plan_factory: Callable[..., SealedWritePlan],
) -> None:
    plan = write_plan_factory()
    tampered = plan.model_dump(mode="json")
    tampered["payload"]["expected_postimage"]["canonical_payload"] = {"paragraph": "tampered"}

    with pytest.raises(ValidationError) as error:
        SealedWritePlan.model_validate(tampered)
    assert "WritePlan integrity mismatch" in str(error.value)
    assert WritePlanIntegrityError.__name__ == "WritePlanIntegrityError"


@pytest.mark.parametrize("forbidden_key", ["targetRevisionId", "replaceAllText"])
def test_unsafe_google_operation_fields_are_rejected(forbidden_key: str) -> None:
    with pytest.raises(ValidationError, match="forbidden Google write field"):
        GoogleDocsBatchUpdate(
            required_revision_id="revision-A",
            requests=({forbidden_key: {"unsafe": True}},),
        )


def test_operation_payload_can_only_emit_required_revision_guard(
    write_plan_factory: Callable[..., SealedWritePlan],
) -> None:
    plan = write_plan_factory()
    operation = plan.payload.provider_operations[0]
    payload = operation.provider_payload()
    assert payload["writeControl"] == {"requiredRevisionId": "revision-A"}
    assert "targetRevisionId" not in str(payload)


def test_operation_revision_must_equal_source_baseline(
    write_plan_factory: Callable[..., SealedWritePlan],
) -> None:
    plan = write_plan_factory()
    payload = plan.payload.model_dump(mode="json")
    payload["provider_operations"][0]["required_revision_id"] = "revision-B"

    with pytest.raises(ValidationError, match="exact baseline revision"):
        type(plan.payload).model_validate(payload)
