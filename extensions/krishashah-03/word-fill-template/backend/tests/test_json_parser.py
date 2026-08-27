import pytest

from app.parsers.json_parser import JSONParseError, parse_json_input


def test_parse_json_string():
    result = parse_json_input('{"name": "Rahul Patel", "ctc": "8 LPA"}')
    assert result == {"name": "Rahul Patel", "ctc": "8 LPA"}


def test_parse_json_flattens_nested_objects():
    result = parse_json_input({"employee": {"name": "Rahul Patel", "remote": True}})
    assert result == {"employee.name": "Rahul Patel", "employee.remote": True}


def test_parse_json_dotted_keys_passthrough():
    result = parse_json_input('{"employee.name": "Rahul Patel"}')
    assert result == {"employee.name": "Rahul Patel"}


def test_parse_json_invalid_string_raises():
    with pytest.raises(JSONParseError):
        parse_json_input("{not valid json")


def test_parse_json_empty_string_raises():
    with pytest.raises(JSONParseError):
        parse_json_input("")


def test_parse_json_empty_object_raises():
    with pytest.raises(JSONParseError):
        parse_json_input({})


def test_parse_json_non_object_top_level_raises():
    with pytest.raises(JSONParseError):
        parse_json_input("[1, 2, 3]")
