import pytest

from app.services.normalization import (
    NormalizationError,
    normalize_boolean,
    normalize_date,
    normalize_number,
    normalize_record,
)

FIELD_SCHEMA = {
    "employee.name": {"type": "string", "required": True},
    "employee.designation": {"type": "string", "required": True},
    "employee.joining_date": {"type": "date", "required": True},
    "employee.ctc": {"type": "number", "required": True},
    "employee.notice_period": {"type": "number", "required": True},
    "employee.location": {"type": "string", "required": False},
    "employee.remote": {"type": "boolean", "required": False},
}


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("8 LPA", 800000),
        ("8 lakh per annum", 800000),
        ("₹8,00,000", 800000),
        ("800000", 800000),
        (800000, 800000),
        ("1 crore", 10_000_000),
    ],
)
def test_normalize_number_salary_formats(raw, expected):
    assert normalize_number(raw) == expected


def test_normalize_number_rejects_unparseable_text():
    with pytest.raises(NormalizationError):
        normalize_number("not a number")


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("2026-09-01", "2026-09-01"),
        ("1 September 2026", "2026-09-01"),
        ("September 1 2026", "2026-09-01"),
        ("1st September 2026", "2026-09-01"),
        ("01/09/2026", "2026-09-01"),
    ],
)
def test_normalize_date_formats(raw, expected):
    assert normalize_date(raw) == expected


def test_normalize_date_rejects_unparseable_text():
    with pytest.raises(NormalizationError):
        normalize_date("sometime next month")


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Yes", True),
        ("No", False),
        (True, True),
        (False, False),
        ("remote", True),
        ("onsite", False),
    ],
)
def test_normalize_boolean_formats(raw, expected):
    assert normalize_boolean(raw) == expected


def test_normalize_boolean_rejects_unparseable_text():
    with pytest.raises(NormalizationError):
        normalize_boolean("maybe")


def test_normalize_record_complete_employee_data():
    raw = {
        "name": "Rahul Patel",
        "designation": "Software Engineer",
        "joining_date": "1 September 2026",
        "ctc": "8 LPA",
        "notice_period": "30 days",
        "location": "Ahmedabad",
        "remote": "Yes",
    }
    normalized, errors = normalize_record(raw, FIELD_SCHEMA)

    assert normalized == {
        "employee.name": "Rahul Patel",
        "employee.designation": "Software Engineer",
        "employee.joining_date": "2026-09-01",
        "employee.ctc": 800000,
        "employee.notice_period": 30,
        "employee.location": "Ahmedabad",
        "employee.remote": True,
    }
    assert errors == {}


def test_normalize_record_missing_notice_period():
    raw = {"name": "Rahul Patel", "ctc": "8 LPA"}
    normalized, errors = normalize_record(raw, FIELD_SCHEMA)

    assert "employee.notice_period" not in normalized
    assert errors == {}


def test_normalize_record_remote_true():
    normalized, _ = normalize_record({"remote": "true"}, FIELD_SCHEMA)
    assert normalized["employee.remote"] is True


def test_normalize_record_remote_false():
    normalized, _ = normalize_record({"remote": "false"}, FIELD_SCHEMA)
    assert normalized["employee.remote"] is False


def test_normalize_record_reports_unparseable_values_as_errors():
    normalized, errors = normalize_record({"ctc": "a lot of money"}, FIELD_SCHEMA)
    assert "employee.ctc" not in normalized
    assert "employee.ctc" in errors
