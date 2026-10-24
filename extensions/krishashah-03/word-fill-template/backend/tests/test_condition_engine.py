from app.services.condition_engine import evaluate_condition


def test_condition_include_when_remote_true():
    result = evaluate_condition("employee.remote", "==", True, "include", {"employee.remote": True})
    assert result.resolved is True
    assert result.include is True


def test_condition_exclude_when_remote_false():
    result = evaluate_condition("employee.remote", "==", True, "include", {"employee.remote": False})
    assert result.resolved is True
    assert result.include is False


def test_condition_unresolved_when_field_missing():
    result = evaluate_condition("employee.remote", "==", True, "include", {})
    assert result.resolved is False
    assert result.include is None


def test_condition_unresolved_when_field_null():
    result = evaluate_condition("employee.remote", "==", True, "include", {"employee.remote": None})
    assert result.resolved is False
    assert result.include is None


def test_condition_not_equal_operator():
    result = evaluate_condition(
        "employee.location", "!=", "Remote", "include", {"employee.location": "Ahmedabad"}
    )
    assert result.include is True


def test_condition_exclude_action_inverts_result():
    result = evaluate_condition("employee.remote", "==", True, "exclude", {"employee.remote": True})
    assert result.include is False
