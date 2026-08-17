from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1]))

from mock_data import load_mock_catalog


def test_properties_load_and_share_the_same_block_ids():
    catalog = load_mock_catalog()
    assert set(catalog.properties) == {"green", "blue"}
    assert catalog.get_property("green").shared_block_ids == catalog.get_property("blue").shared_block_ids
    assert catalog.blocks_for(catalog.get_property("green"))[0] is catalog.shared_block("quiet-hours")


def test_property_specific_fields_are_independent():
    catalog = load_mock_catalog()
    green, blue = catalog.get_property("green"), catalog.get_property("blue")
    original_blue_wifi = blue.wifi_password
    green.wifi_password = "changed-green-only"
    assert blue.wifi_password == original_blue_wifi
