"""Platform-ready rental listing descriptions derived from canonical content."""

from __future__ import annotations

from typing import Any


# Kept as a named policy so operators can align it with a chosen platform.
LISTING_MAX_CHARS = 1_500

# Sentence templates per supported language. English is the canonical fallback.
_TEMPLATES = {
    "en": {
        "intro": (
            "Relax in this {property_type} in {address}. The home has {bedrooms} bedrooms, "
            "{bathrooms} bathrooms, and welcomes up to {maximum_guests} guests."
        ),
        "amenities": "Amenities: {amenities}. Wi-Fi: {wifi_network}.",
        "stay": "Check-in: {check_in} | Check-out: {check_out}",
        "rules": "House rules: {rules}; maximum {maximum_guests} guests.",
        "nearby": "Nearby: {nearby}.",
    },
    "kn": {
        "intro": (
            "{address} ನಲ್ಲಿರುವ ಈ {property_type} ನಲ್ಲಿ ಆರಾಮವಾಗಿ ಉಳಿಯಿರಿ. "
            "ಮನೆಯಲ್ಲಿ {bedrooms} ಮಲಗುವ ಕೊಠಡಿಗಳು, {bathrooms} ಸ್ನಾನಗೃಹಗಳಿವೆ ಮತ್ತು ಗರಿಷ್ಠ "
            "{maximum_guests} ಅತಿಥಿಗಳನ್ನು ಸ್ವೀಕರಿಸಲಾಗುತ್ತದೆ."
        ),
        "amenities": "ಸೌಲಭ್ಯಗಳು: {amenities}. ವೈ-ಫೈ: {wifi_network}.",
        "stay": "ಚೆಕ್-ಇನ್: {check_in} | ಚೆಕ್-ಔಟ್: {check_out}",
        "rules": "ಮನೆಯ ನಿಯಮಗಳು: {rules}; ಗರಿಷ್ಠ {maximum_guests} ಅತಿಥಿಗಳು.",
        "nearby": "ಹತ್ತಿರದಲ್ಲಿವೆ: {nearby}.",
    },
}


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
    templates = _TEMPLATES.get(content.get("language", "en"), _TEMPLATES["en"])
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
    context = {**property_data, "amenities": amenities, "nearby": nearby, "rules": rules}
    listing = "\n\n".join(
        (
            f"{property_data['name']} — {property_data['unit']}",
            templates["intro"].format(**context),
            templates["amenities"].format(**context),
            templates["stay"].format(**context),
            templates["rules"].format(**context),
            templates["nearby"].format(**context),
        )
    )
    validate_listing_length(listing, maximum=maximum)
    return listing
