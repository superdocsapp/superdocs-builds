from app.services.template_engine import build_template_result

FIELD_SCHEMA = {
    "employee.name": {"type": "string", "required": True},
    "employee.notice_period": {"type": "number", "required": True},
    "employee.remote": {"type": "boolean", "required": False},
}

CONDITIONS = [
    {"condition_key": "employee.remote", "operator": "==", "expected_value": True, "action": "include"},
]


def test_build_template_result_ready_field():
    normalized_data = {"employee.name": "Rahul Patel", "employee.remote": True}
    gaps = [{"field": "employee.notice_period", "reason": "Required field is missing"}]

    result = build_template_result(FIELD_SCHEMA, CONDITIONS, normalized_data, gaps)
    changes_by_field = {change["field"]: change for change in result["proposed_changes"]}

    assert changes_by_field["employee.name"]["status"] == "ready"
    assert changes_by_field["employee.name"]["proposed_value"] == "Rahul Patel"
    assert changes_by_field["employee.name"]["placeholder"] == "{{employee.name}}"


def test_build_template_result_missing_field_never_filled_in():
    result = build_template_result(
        FIELD_SCHEMA,
        CONDITIONS,
        {"employee.name": "Rahul Patel"},
        [{"field": "employee.notice_period", "reason": "Required field is missing"}],
    )
    changes_by_field = {change["field"]: change for change in result["proposed_changes"]}

    assert changes_by_field["employee.notice_period"]["status"] == "missing"
    assert changes_by_field["employee.notice_period"]["proposed_value"] is None


def test_build_template_result_condition_included_when_remote_true():
    result = build_template_result(
        FIELD_SCHEMA, CONDITIONS, {"employee.name": "Rahul", "employee.remote": True}, []
    )
    assert result["conditions"][0]["include"] is True


def test_build_template_result_condition_excluded_when_remote_false():
    result = build_template_result(
        FIELD_SCHEMA, CONDITIONS, {"employee.name": "Rahul", "employee.remote": False}, []
    )
    assert result["conditions"][0]["include"] is False


def test_build_template_result_condition_unresolved_when_field_missing():
    result = build_template_result(FIELD_SCHEMA, CONDITIONS, {"employee.name": "Rahul"}, [])
    assert result["conditions"][0]["resolved"] is False
    assert result["conditions"][0]["include"] is None
