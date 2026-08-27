import pytest

from app.parsers.csv_parser import CSVParseError, parse_csv_input


def test_parse_csv_basic_row():
    csv_text = "name,ctc,notice_period\nRahul Patel,8 LPA,30"
    result = parse_csv_input(csv_text)
    assert result["name"] == "Rahul Patel"
    assert result["ctc"] == "8 LPA"
    assert result["notice_period"] == 30


def test_parse_csv_uses_first_row_only():
    csv_text = "name,ctc\nRahul Patel,8 LPA\nSecond Person,9 LPA"
    result = parse_csv_input(csv_text)
    assert result["name"] == "Rahul Patel"


def test_parse_csv_skips_missing_values():
    csv_text = "name,location\nRahul Patel,"
    result = parse_csv_input(csv_text)
    assert "location" not in result


def test_parse_csv_empty_raises():
    with pytest.raises(CSVParseError):
        parse_csv_input("")


def test_parse_csv_no_data_rows_raises():
    with pytest.raises(CSVParseError):
        parse_csv_input("name,ctc\n")


def test_parse_csv_invalid_content_raises():
    with pytest.raises(CSVParseError):
        parse_csv_input(None)
