from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from app.models import Violation
from app.offline import generate_offline_plan
from app.template import build_plan_template_html
from app.verifier import verify_coverage


FIXTURES = Path(__file__).parent / "fixtures"


def load_case() -> tuple[str, date, str, tuple[Violation, ...]]:
    payload = json.loads((FIXTURES / "violations.json").read_text(encoding="utf-8"))
    return (
        payload["restaurant"],
        date.fromisoformat(payload["inspection_date"]),
        payload["health_department"],
        tuple(Violation(**violation) for violation in payload["violations"]),
    )


def test_offline_generator_produces_one_verified_item_per_violation() -> None:
    restaurant, inspection_date, department, violations = load_case()

    plan = generate_offline_plan(
        restaurant=restaurant,
        inspection_date=inspection_date,
        health_department=department,
        violations=violations,
    )

    report = verify_coverage(violations, plan)
    assert report.is_complete
    assert [item.code for item in plan.items] == ["5-202.11", "3-501.16", "6-501.12"]
    assert len({item.corrective_action for item in plan.items}) == 3
    assert [item.responsible_party for item in plan.items] == [
        "Facilities Lead",
        "Kitchen Manager",
        "Closing Supervisor",
    ]


def test_template_has_one_structural_section_per_violation_code() -> None:
    restaurant, inspection_date, department, violations = load_case()

    html = build_plan_template_html(
        restaurant=restaurant,
        inspection_date=inspection_date,
        health_department=department,
        violations=violations,
    )

    for violation in violations:
        assert html.count(f'data-violation-code="{violation.code}"') == 1
        assert f"Violation {violation.code}" in html
    assert html.count('data-slot="corrective-action"') == 3
    assert html.count('data-slot="responsible-party"') == 3
    assert html.count('data-slot="evidence"') == 3

