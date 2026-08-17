from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1]))

from content_generator import get_property_canonical_content
from mock_data import load_mock_catalog
from shared_content_demo import demonstrate_shared_content_propagation


def test_canonical_content_includes_shared_and_property_specific_data():
    content = get_property_canonical_content(load_mock_catalog(), "green")
    assert content["property"]["wifi_network"] == "GreenGuest"
    assert any(block["id"] == "quiet-hours" for block in content["shared_blocks"])
    assert len(content["appliances"]) == 6


def test_kannada_and_unknown_language_fallback_are_explicit():
    catalog = load_mock_catalog()
    kannada = get_property_canonical_content(catalog, "green", "kn")
    fallback = get_property_canonical_content(catalog, "green", "fr")
    assert kannada["language"] == "kn"
    assert kannada["property"]["name"] != "Green Residency"
    assert fallback["language"] == "en"
    assert fallback["language_fallback"] is True


def test_shared_updates_propagate_without_clobbering_property_data():
    result = demonstrate_shared_content_propagation()
    assert result["shared_rule_updated"]["green_received_update"]
    assert result["shared_rule_updated"]["blue_received_update"]
    assert result["property_specific_update"]["blue_unchanged"]
