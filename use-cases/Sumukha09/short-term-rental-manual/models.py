"""Data models for the Task 2A rental-property document use case.

The models intentionally keep shared content separate from a property's own
data.  A ``Property`` stores references to ``SharedBlock`` ids rather than
copies of rule or policy text.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
@dataclass
class Appliance:
    """An appliance available at one specific property."""

    name: str
    instructions: str
    language_variants: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass
class LocalRecommendation:
    """A nearby place recommended to guests."""

    category: str
    name: str
    description: str
    distance: str
    language_variants: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass
class Photo:
    """A real property photograph to embed in the generated document."""

    path: Path
    caption: str
    alt_text: str
    language_variants: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass
class MapDiagram:
    """A printable local wayfinding diagram."""

    path: Path
    caption: str
    alt_text: str
    language_variants: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass
class SharedBlock:
    """Reusable operator-managed content, referenced by id from properties."""

    id: str
    block_type: str
    title: str
    content: str
    language_variants: dict[str, dict[str, Any]] = field(default_factory=dict)
    version: int = 1

    def update_content(self, content: str, *, language: str = "en") -> None:
        """Update a shared block in one place and advance its version.

        English is the canonical source.  Translated variants may be updated
        independently by passing their language code.
        """
        if language == "en":
            self.content = content
        else:
            variant = self.language_variants.setdefault(language, {})
            variant["content"] = content
        self.version += 1


@dataclass
class Property:
    """Property-specific rental data; never contains copied shared-block text."""

    id: str
    name: str
    unit: str
    address: str
    property_type: str
    bedrooms: int
    bathrooms: int
    maximum_guests: int
    check_in: str
    check_out: str
    access_instructions: str
    wifi_network: str
    wifi_password: str
    appliances: list[Appliance]
    local_recommendations: list[LocalRecommendation]
    emergency_information: dict[str, str]
    photos: list[Photo]
    map_diagram: MapDiagram
    shared_block_ids: list[str]
    language_variants: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass
class PropertyCatalog:
    """In-memory source of truth used by generators and offline tests."""

    properties: dict[str, Property]
    shared_blocks: dict[str, SharedBlock]

    def get_property(self, property_id: str) -> Property:
        return self.properties[property_id]

    def blocks_for(self, property: Property) -> list[SharedBlock]:
        """Resolve blocks in the property's declared display order."""
        return [self.shared_blocks[block_id] for block_id in property.shared_block_ids]

    def shared_block(self, block_id: str) -> SharedBlock:
        return self.shared_blocks[block_id]
