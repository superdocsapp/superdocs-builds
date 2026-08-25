import pytest

from backend.app.services.readiness import calculate_readiness

TEMPLATE_TYPES = ["Trial Balance", "Revenue"]


def base_close(**overrides):
    close = {
        "required_document_types": list(TEMPLATE_TYPES),
        "documents": [],
        "checklist": [],
        "reviews": [],
        "signoffs": [],
        "superdocs_document_ids": [],
        "exported": False,
    }
    close.update(overrides)
    return close


def test_empty_close_does_not_divide_by_zero():
    """The previous implementation raised ZeroDivisionError and 500ed the endpoint."""
    result = calculate_readiness(base_close(required_document_types=[]))

    assert result["ready_for_close"] is False
    assert isinstance(result["readiness"], int)


@pytest.mark.parametrize("missing", ["documents", "checklist", "reviews", "signoffs", "export", "generation"])
def test_each_dimension_independently_blocks_the_close(missing):
    close = base_close(
        documents=[
            {"document_type": "Trial Balance", "status": "READY"},
            {"document_type": "Revenue", "status": "READY"},
        ],
        checklist=[{"status": "COMPLETE"}],
        reviews=[{"status": "APPROVED"}],
        signoffs=[{"status": "APPROVED"}],
        superdocs_document_ids=["sd-1"],
        exported=True,
    )

    if missing == "documents":
        close["documents"][1]["status"] = "PROCESSING"
    elif missing == "checklist":
        close["checklist"][0]["status"] = "PENDING"
    elif missing == "reviews":
        close["reviews"][0]["status"] = "PENDING"
    elif missing == "signoffs":
        close["signoffs"][0]["status"] = "PENDING"
    elif missing == "generation":
        close["superdocs_document_ids"] = []
    else:
        close["exported"] = False

    result = calculate_readiness(close)

    assert result["ready_for_close"] is False
    assert result["blockers"]


def test_documents_are_measured_against_required_types_not_uploads():
    """Uploading eight copies of the same type must not satisfy the requirement."""
    close = base_close(
        documents=[{"document_type": "Trial Balance", "status": "READY"} for _ in range(8)],
    )

    result = calculate_readiness(close)

    assert result["documents"] == {
        "required": 2,
        "present": 1,
        "missing_types": ["Revenue"],
        "unclassified": 0,
    }
    assert result["ready_for_generation"] is False


def test_close_becomes_ready_when_every_dimension_is_satisfied():
    close = base_close(
        documents=[
            {"document_type": "Trial Balance", "status": "READY"},
            {"document_type": "Revenue", "status": "READY"},
        ],
        checklist=[{"status": "COMPLETE"}],
        reviews=[{"status": "APPROVED"}, {"status": "REJECTED"}],
        signoffs=[{"status": "APPROVED"}],
        superdocs_document_ids=["sd-1"],
        exported=True,
    )

    result = calculate_readiness(close)

    assert result["ready_for_close"] is True
    assert result["blockers"] == []
    assert result["readiness"] == 100


def test_blocker_wording_is_singular_or_plural_correctly():
    close = base_close(checklist=[{"status": "PENDING"}])
    assert "1 checklist item pending" in calculate_readiness(close)["blockers"]

    close = base_close(checklist=[{"status": "PENDING"}, {"status": "PENDING"}])
    assert "2 checklist items pending" in calculate_readiness(close)["blockers"]
