"""Platform-ready rental listing descriptions derived from canonical content."""

from __future__ import annotations

from typing import Any


# Kept as a named policy so operators can align it with a chosen platform.
LISTING_MAX_CHARS = 1_500


class ListingLengthError(ValueError):
    """Raised when a listing exceeds the configured platform allowance."""


def validate_listing_length(listing: str, *, maximum: int = LISTING_MAX_CHARS) -> None:
    """Validate rather than silently truncate operator-facing listing copy."""
    if len(listing) > maximum:
        raise ListingLengthError(
            f"Listing is {len(listing)} characters; platform maximum is {maximum}."
        )


def generate_listing_description(
    content: dict[str, Any], *, maximum: int = LISTING_MAX_CHARS
) -> str:
    """Build listing copy from one canonical property projection.

    Nothing is read directly from mock data here, ensuring the listing stays in
    sync with the manual and welcome card as a property changes.
    """
    property_data = content["property"]
    amenities = ", ".join(appliance["name"] for appliance in content["appliances"])
    nearby = ", ".join(
        f"{recommendation['name']} ({recommendation['distance']})"
        for recommendation in content["local_recommendations"]
    )
    rules = "; ".join(
        block["title"]
        for block in content["shared_blocks"]
        if block["block_type"] == "house_rule"
    )
    listing = (
        f"{property_data['name']} — {property_data['unit']}\n\n"
        f"Relax in this {property_data['property_type']} in {property_data['address']}. "
        f"The home has {property_data['bedrooms']} bedrooms, {property_data['bathrooms']} bathrooms, "
        f"and welcomes up to {property_data['maximum_guests']} guests.\n\n"
        f"Amenities: {amenities}. Wi-Fi: {property_data['wifi_network']}.\n\n"
        f"Check-in: {property_data['check_in']} | Check-out: {property_data['check_out']}\n\n"
        f"House rules: {rules}; maximum {property_data['maximum_guests']} guests.\n\n"
        f"Nearby: {nearby}."
    )
    validate_listing_length(listing, maximum=maximum)
    return listing
