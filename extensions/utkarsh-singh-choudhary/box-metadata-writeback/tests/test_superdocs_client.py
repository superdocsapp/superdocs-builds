import json

from app.clients.superdocs_client import parse_proposed_change


def test_parses_json_encoded_string_the_documented_quirk():
    raw = json.dumps({"doc_class": "contract", "confidence": 0.9})
    result = parse_proposed_change(raw)
    assert result == {"doc_class": "contract", "confidence": 0.9}


def test_leniently_accepts_already_decoded_dict():
    result = parse_proposed_change({"doc_class": "invoice"})
    assert result == {"doc_class": "invoice"}


def test_none_and_malformed_input_return_none_not_a_crash():
    assert parse_proposed_change(None) is None
    assert parse_proposed_change("{not valid json") is None
