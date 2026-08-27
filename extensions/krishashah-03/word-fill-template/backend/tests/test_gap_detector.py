from app.services.gap_detector import detect_gaps

FIELD_SCHEMA = {
    "employee.name": {"type": "string", "required": True},
    "employee.designation": {"type": "string", "required": True},
    "employee.notice_period": {"type": "number", "required": True},
    "employee.location": {"type": "string", "required": False},
}


def test_detect_gaps_reports_missing_required_fields():
    normalized = {"employee.name": "Rahul Patel"}
    gaps = detect_gaps(normalized, FIELD_SCHEMA)
    assert {gap["field"] for gap in gaps} == {"employee.designation", "employee.notice_period"}


def test_detect_gaps_none_when_all_required_fields_present():
    normalized = {
        "employee.name": "Rahul Patel",
        "employee.designation": "Software Engineer",
        "employee.notice_period": 30,
    }
    assert detect_gaps(normalized, FIELD_SCHEMA) == []


def test_detect_gaps_ignores_optional_fields():
    normalized = {
        "employee.name": "Rahul Patel",
        "employee.designation": "Software Engineer",
        "employee.notice_period": 30,
    }
    gaps = detect_gaps(normalized, FIELD_SCHEMA)
    assert not any(gap["field"] == "employee.location" for gap in gaps)


def test_detect_gaps_never_invents_a_value():
    gaps = detect_gaps({}, FIELD_SCHEMA)
    for gap in gaps:
        assert "resolved_value" not in gap
