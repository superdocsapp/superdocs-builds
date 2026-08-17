"""Build the canonical, language-aware content used by every output.

This module deliberately produces content only.  It has no dependency on HTML,
PDF, or SuperDocs so it is inexpensive to test and reuse.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from models import (
    Appliance,
    LocalRecommendation,
    MapDiagram,
    Photo,
    Property,
    PropertyCatalog,
    SharedBlock,
)


SUPPORTED_LANGUAGES = {"en", "kn"}

_LABELS = {
    "en": {
        "guest_house_manual": "Guest House Manual",
        "welcome_to": "Welcome to",
        "welcome": "Welcome",
        "property_overview": "Property Overview",
        "arrival_checkin": "Arrival & Check-in",
        "wifi": "Wi-Fi",
        "network": "Network",
        "password": "Password",
        "appliances": "Appliances",
        "house_rules": "House Rules",
        "local_recommendations": "Local Recommendations",
        "emergency_information": "Emergency Information",
        "checkout": "Check-out",
        "photos": "Photos",
        "location_map": "Location & Map",
        "bedrooms": "Bedrooms",
        "property_type": "Type",
        "bathrooms": "Bathrooms",
        "maximum_guests": "Maximum guests",
        "check_in": "Check-in",
        "check_out": "Check-out",
        "access_instructions": "Access instructions",
        "emergency_number": "Emergency number",
        "property_manager": "Property manager",
        "hospital": "Hospital",
    },
    "kn": {
        "guest_house_manual": "ಅತಿಥಿ ಮನೆ ಕೈಪಿಡಿ",
        "welcome_to": "ಸುಸ್ವಾಗತ",
        "welcome": "ಸ್ವಾಗತ",
        "property_overview": "ಆಸ್ತಿ ವಿವರ",
        "arrival_checkin": "ಆಗಮನ ಮತ್ತು ಚೆಕ್-ಇನ್",
        "wifi": "ವೈ-ಫೈ",
        "network": "ನೆಟ್‌ವರ್ಕ್",
        "password": "ಪಾಸ್‌ವರ್ಡ್",
        "appliances": "ಉಪಕರಣಗಳು",
        "house_rules": "ಮನೆಯ ನಿಯಮಗಳು",
        "local_recommendations": "ಸ್ಥಳೀಯ ಶಿಫಾರಸುಗಳು",
        "emergency_information": "ತುರ್ತು ಮಾಹಿತಿ",
        "checkout": "ಚೆಕ್-ಔಟ್",
        "photos": "ಚಿತ್ರಗಳು",
        "location_map": "ಸ್ಥಳ ಮತ್ತು ನಕ್ಷೆ",
        "bedrooms": "ಮಲಗುವ ಕೊಠಡಿಗಳು",
        "property_type": "ಆಸ್ತಿ ಪ್ರಕಾರ",
        "bathrooms": "ಸ್ನಾನಗೃಹಗಳು",
        "maximum_guests": "ಗರಿಷ್ಠ ಅತಿಥಿಗಳು",
        "check_in": "ಚೆಕ್-ಇನ್",
        "check_out": "ಚೆಕ್-ಔಟ್",
        "access_instructions": "ಪ್ರವೇಶ ಸೂಚನೆಗಳು",
        "emergency_number": "ತುರ್ತು ಸಂಖ್ಯೆ",
        "property_manager": "ಆಸ್ತಿ ವ್ಯವಸ್ಥಾಪಕರು",
        "hospital": "ಆಸ್ಪತ್ರೆ",
    },
}


def _language(language: str) -> str:
    """Return a supported language code, with English as explicit fallback."""
    return language if language in SUPPORTED_LANGUAGES else "en"


def _localized(value: Any, language: str, *fields: str) -> dict[str, Any]:
    """Project selected fields, recording which ones fell back to English."""
    variants = getattr(value, "language_variants", {}).get(language, {})
    result: dict[str, Any] = {}
    fallback_fields: list[str] = []
    for field in fields:
        translated = variants.get(field)
        if translated is None:
            result[field] = getattr(value, field)
            if language != "en":
                fallback_fields.append(field)
        else:
            result[field] = translated
    if fallback_fields:
        result["fallback_fields"] = fallback_fields
    return result


def _photo_content(photo: Photo, language: str) -> dict[str, Any]:
    result = _localized(photo, language, "caption", "alt_text")
    result["path"] = str(photo.path)
    return result


def _map_content(map_diagram: MapDiagram, language: str) -> dict[str, Any]:
    result = _localized(map_diagram, language, "caption", "alt_text")
    result["path"] = str(map_diagram.path)
    return result


def get_canonical_content(
    property: Property,
    language: str = "en",
    *,
    shared_blocks: Mapping[str, SharedBlock],
) -> dict[str, Any]:
    """Combine one property with its referenced shared blocks.

    ``shared_blocks`` is passed separately on purpose: it keeps the Property
    model free of duplicated policy text and makes a shared-block change visible
    to every property the next time this function is called.
    """
    requested_language = language
    language = _language(language)
    property_text = _localized(
        property, language, "name", "property_type", "address", "unit", "access_instructions", "check_in", "check_out", "wifi_network", "wifi_password"
    )
    welcome_message = property.language_variants.get(language, {}).get(
        "welcome_message",
        f"Welcome to {property_text['name']}. We are delighted to host you.",
    )

    blocks = []
    for block_id in property.shared_block_ids:
        block = shared_blocks[block_id]
        block_text = _localized(block, language, "title", "content")
        blocks.append({"id": block.id, "block_type": block.block_type, "version": block.version, **block_text})

    appliances = [_localized(appliance, language, "name", "instructions") for appliance in property.appliances]
    recommendations = [
        _localized(recommendation, language, "category", "name", "description", "distance")
        for recommendation in property.local_recommendations
    ]

    localized_emergency = property.language_variants.get(language, {}).get(
        "emergency_information", dict(property.emergency_information)
    )
    fallback_sections = []
    if language != "en" and "emergency_information" not in property.language_variants.get(language, {}):
        fallback_sections.append("emergency_information")

    return {
        "language": language,
        "requested_language": requested_language,
        "language_fallback": requested_language != language,
        "labels": _LABELS[language],
        "title": f"{_LABELS[language]['welcome_to']} {property_text['name']}",
        "welcome_message": welcome_message,
        "property": {
            "id": property.id,
            **property_text,
            "bedrooms": property.bedrooms,
            "bathrooms": property.bathrooms,
            "maximum_guests": property.maximum_guests,
        },
        "appliances": appliances,
        "local_recommendations": recommendations,
        "emergency_information": localized_emergency,
        "fallback_sections": fallback_sections,
        "shared_blocks": blocks,
        "photos": [_photo_content(photo, language) for photo in property.photos],
        "map_diagram": _map_content(property.map_diagram, language),
    }


def get_property_canonical_content(
    catalog: PropertyCatalog, property_id: str, language: str = "en"
) -> dict[str, Any]:
    """Convenience entry point for scripts and tests using a catalog."""
    property = catalog.get_property(property_id)
    return get_canonical_content(property, language, shared_blocks=catalog.shared_blocks)
