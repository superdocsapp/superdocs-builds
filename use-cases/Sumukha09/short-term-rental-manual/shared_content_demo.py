"""Executable proof that shared content propagates without clobbering properties."""

from __future__ import annotations

from typing import Any

from content_generator import get_property_canonical_content
from mock_data import load_mock_catalog


UPDATED_QUIET_HOURS = (
    "Quiet hours are from 10 PM to 8 AM. Please keep music, TV, and conversations low during this time."
)
UPDATED_GREEN_WIFI_PASSWORD = "GREEN-UPDATED-PASSWORD"


def _block_content(content: dict[str, Any], block_id: str) -> str:
    return next(block["content"] for block in content["shared_blocks"] if block["id"] == block_id)


def demonstrate_shared_content_propagation() -> dict[str, Any]:
    """Run the required shared-update and property-isolation demonstration.

    A new in-memory catalog is used for every run, so this function is safe for
    preview commands and tests.  The function never writes the mock source data.
    """
    catalog = load_mock_catalog()
    green = catalog.get_property("green")
    blue = catalog.get_property("blue")
    original_green_wifi = green.wifi_password
    original_blue_wifi = blue.wifi_password

    # One block object is shared by id; no text is copied into either property.
    catalog.shared_block("quiet-hours").update_content(UPDATED_QUIET_HOURS)
    green_after_rule = get_property_canonical_content(catalog, "green")
    blue_after_rule = get_property_canonical_content(catalog, "blue")

    # This intentionally changes only the Green property record.
    green.wifi_password = UPDATED_GREEN_WIFI_PASSWORD
    green_after_wifi = get_property_canonical_content(catalog, "green")
    blue_after_wifi = get_property_canonical_content(catalog, "blue")

    result = {
        "shared_rule_updated": {
            "new_content": UPDATED_QUIET_HOURS,
            "green_received_update": _block_content(green_after_rule, "quiet-hours") == UPDATED_QUIET_HOURS,
            "blue_received_update": _block_content(blue_after_rule, "quiet-hours") == UPDATED_QUIET_HOURS,
        },
        "property_specific_update": {
            "green_password_before": original_green_wifi,
            "green_password_after": green_after_wifi["property"]["wifi_password"],
            "blue_password_before": original_blue_wifi,
            "blue_password_after": blue_after_wifi["property"]["wifi_password"],
            "blue_unchanged": blue_after_wifi["property"]["wifi_password"] == original_blue_wifi,
        },
    }
    assert result["shared_rule_updated"]["green_received_update"]
    assert result["shared_rule_updated"]["blue_received_update"]
    assert result["property_specific_update"]["green_password_after"] == UPDATED_GREEN_WIFI_PASSWORD
    assert result["property_specific_update"]["blue_unchanged"]
    return result


if __name__ == "__main__":
    result = demonstrate_shared_content_propagation()
    print("Shared rule update: Green Residency OK | Blue Residency OK")
    print("Property-specific Wi-Fi update: Green Residency OK | Blue Residency unchanged OK")
