"""End-to-end normalize -> gap-detect -> condition-evaluate pipeline tests.

These simulate the raw field values a natural-language / email / bullet-point
input would produce once the AI extraction step (mocked here, since it calls
an external API) hands off to the deterministic pipeline.
"""

from app.services.gap_detector import detect_gaps
from app.services.normalization import normalize_record
from app.services.template_engine import build_template_result

FIELD_SCHEMA = {
    "employee.name": {"type": "string", "required": True},
    "employee.designation": {"type": "string", "required": True},
    "employee.joining_date": {"type": "date", "required": True},
    "employee.ctc": {"type": "number", "required": True},
    "employee.notice_period": {"type": "number", "required": True},
    "employee.location": {"type": "string", "required": False},
    "employee.remote": {"type": "boolean", "required": False},
}

CONDITIONS = [
    {"condition_key": "employee.remote", "operator": "==", "expected_value": True, "action": "include"},
]


def _run_pipeline(raw_data: dict) -> dict:
    normalized_data, _ = normalize_record(raw_data, FIELD_SCHEMA)
    gaps = detect_gaps(normalized_data, FIELD_SCHEMA)
    template_result = build_template_result(FIELD_SCHEMA, CONDITIONS, normalized_data, gaps)
    return {"normalized_data": normalized_data, "gaps": gaps, **template_result}


def test_natural_language_style_extraction_produces_complete_record():
    # Simulated AI extraction output for:
    # "Create salary structure for Rahul Patel. He is joining on 1 September 2026
    #  as a Software Engineer. His CTC is 8 LPA. His notice period is 30 days.
    #  He is based in Ahmedabad and works remotely."
    raw_data = {
        "employee.name": "Rahul Patel",
        "employee.designation": "Software Engineer",
        "employee.joining_date": "1 September 2026",
        "employee.ctc": "8 LPA",
        "employee.notice_period": "30 days",
        "employee.location": "Ahmedabad",
        "employee.remote": "true",
    }

    result = _run_pipeline(raw_data)

    assert result["normalized_data"]["employee.joining_date"] == "2026-09-01"
    assert result["normalized_data"]["employee.ctc"] == 800000
    assert result["normalized_data"]["employee.remote"] is True
    assert result["gaps"] == []
    assert result["conditions"][0]["include"] is True


def test_email_style_extraction_with_missing_notice_period():
    # Simulated AI extraction output for a pasted offer email that never
    # mentions a notice period.
    raw_data = {
        "employee.name": "Rahul Patel",
        "employee.designation": "Software Engineer",
        "employee.joining_date": "2026-09-01",
        "employee.ctc": "800000",
        "employee.notice_period": None,
        "employee.location": "Ahmedabad",
        "employee.remote": None,
    }

    result = _run_pipeline(raw_data)

    assert result["gaps"] == [{"field": "employee.notice_period", "reason": "Required field is missing"}]
    changes_by_field = {change["field"]: change for change in result["proposed_changes"]}
    assert changes_by_field["employee.notice_period"]["status"] == "missing"
    assert changes_by_field["employee.notice_period"]["proposed_value"] is None
    assert result["conditions"][0]["resolved"] is False


def test_bullet_point_style_extraction_with_remote_false():
    # Simulated AI extraction output for:
    # "- Name: Rahul Patel
    #  - Role: Software Engineer
    #  - Joining: 1 Sept 2026
    #  - CTC: 8 LPA
    #  - Notice: 30 days
    #  - Location: Ahmedabad (on-site)"
    raw_data = {
        "employee.name": "Rahul Patel",
        "employee.designation": "Software Engineer",
        "employee.joining_date": "1 Sept 2026",
        "employee.ctc": "8 LPA",
        "employee.notice_period": "30",
        "employee.location": "Ahmedabad",
        "employee.remote": "onsite",
    }

    result = _run_pipeline(raw_data)

    assert result["normalized_data"]["employee.remote"] is False
    assert result["gaps"] == []
    assert result["conditions"][0]["include"] is False
