from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.models import CorrectivePlan, Violation
from app.verifier import verify_coverage


FIXTURES = Path(__file__).parent / "fixtures"


def load_violations() -> tuple[Violation, ...]:
    payload = json.loads((FIXTURES / "violations.json").read_text(encoding="utf-8"))
    return tuple(Violation(**violation) for violation in payload["violations"])


def load_plan(name: str) -> CorrectivePlan:
    return CorrectivePlan(**json.loads((FIXTURES / name).read_text(encoding="utf-8")))


def reasons(report) -> dict[str, tuple[str, ...]]:
    return {code.code: code.reasons for code in report.codes}


def test_good_plan_covers_each_violation_code_individually() -> None:
    report = verify_coverage(load_violations(), load_plan("good_plan.json"))

    assert report.is_complete
    assert [code.code for code in report.codes] == ["5-202.11", "3-501.16", "6-501.12"]
    assert all(not code.reasons for code in report.codes)


def test_blended_one_paragraph_plan_is_rejected() -> None:
    report = verify_coverage(load_violations(), load_plan("blended_plan.json"))

    assert not report.is_complete
    by_code = reasons(report)
    assert "corrective action is copied from another violation" in by_code["5-202.11"]
    assert "responsible party is copied from another violation" in by_code["3-501.16"]
    assert "corrective action is copied from another violation" in by_code["6-501.12"]


def test_individually_coded_boilerplate_plan_is_rejected() -> None:
    report = verify_coverage(load_violations(), load_plan("boilerplate_plan.json"))

    assert not report.is_complete
    for code_report in report.codes:
        assert (
            "corrective action is boilerplate and not specific to the violation"
            in code_report.reasons
        )
        assert "corrective action is near-identical to another violation" in code_report.reasons


def test_missing_violation_code_or_description_names_field() -> None:
    with pytest.raises(ValidationError) as missing_code:
        Violation(code="", description="A valid finding")
    assert "code" in str(missing_code.value)

    with pytest.raises(ValidationError) as missing_description:
        Violation(code="5-202.11", description=" ")
    assert "description" in str(missing_description.value)


def test_corrective_item_without_action_or_owner_cannot_construct() -> None:
    payload = json.loads((FIXTURES / "good_plan.json").read_text(encoding="utf-8"))
    payload["items"][0]["corrective_action"] = ""
    payload["items"][1]["responsible_party"] = " "

    with pytest.raises(ValidationError) as error:
        CorrectivePlan(**payload)

    message = str(error.value)
    assert "corrective_action" in message
    assert "responsible_party" in message

