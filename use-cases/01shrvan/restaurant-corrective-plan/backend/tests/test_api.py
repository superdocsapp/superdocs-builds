from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.api import create_app
from app.models import CorrectivePlan
from app.review import ReviewItem, apply_decision


FIXTURES = Path(__file__).parent / "fixtures"


def client() -> TestClient:
    return TestClient(create_app())


def sample_payload() -> dict:
    return json.loads((FIXTURES / "violations.json").read_text(encoding="utf-8"))


def test_draft_endpoint_returns_verified_offline_plan() -> None:
    response = client().post("/api/draft", json=sample_payload())

    assert response.status_code == 200
    payload = response.json()
    assert payload["coverage"]["is_complete"] is True
    assert [item["code"] for item in payload["plan"]["items"]] == [
        "5-202.11",
        "3-501.16",
        "6-501.12",
    ]
    assert payload["template_html"].count("data-violation-code=") == 3


def test_rejecting_one_item_leaves_other_review_items_untouched_by_identity() -> None:
    plan = CorrectivePlan(**json.loads((FIXTURES / "good_plan.json").read_text()))
    original = tuple(ReviewItem(item=item) for item in plan.items)

    updated = apply_decision(original, code="3-501.16", decision="rejected")

    assert updated[0] is original[0]
    assert updated[1] is not original[1]
    assert updated[1].decision == "rejected"
    assert updated[2] is original[2]


def test_export_is_refused_while_any_item_is_undecided_and_names_code() -> None:
    draft = client().post("/api/draft", json=sample_payload()).json()
    decisions = {"5-202.11": "approved", "3-501.16": "approved"}

    response = client().post(
        "/api/export",
        json={
            "plan": draft["plan"],
            "violations": sample_payload()["violations"],
            "decisions": decisions,
            "format": "html",
        },
    )

    assert response.status_code == 409
    assert "6-501.12" in response.json()["detail"]
    assert "Approve or reject each item" in response.json()["detail"]


def test_export_is_refused_when_coverage_is_incomplete_and_names_missing_code() -> None:
    plan = json.loads((FIXTURES / "good_plan.json").read_text(encoding="utf-8"))
    plan["items"] = plan["items"][:2]
    decisions = {"5-202.11": "approved", "3-501.16": "approved"}

    response = client().post(
        "/api/export",
        json={
            "plan": plan,
            "violations": sample_payload()["violations"],
            "decisions": decisions,
            "format": "html",
        },
    )

    assert response.status_code == 409
    assert "6-501.12" in response.json()["detail"]
    assert "coverage is incomplete" in response.json()["detail"]


def test_export_rejects_md_with_cause_and_fix() -> None:
    draft = client().post("/api/draft", json=sample_payload()).json()
    decisions = {item["code"]: "approved" for item in draft["plan"]["items"]}

    response = client().post(
        "/api/export",
        json={
            "plan": draft["plan"],
            "violations": sample_payload()["violations"],
            "decisions": decisions,
            "format": "md",
        },
    )

    assert response.status_code == 400
    assert (
        response.json()["detail"]
        == "export failed: format 'md' is not valid. Use 'doc', 'docx', 'html', 'markdown', 'pdf', 'txt'."
    )

