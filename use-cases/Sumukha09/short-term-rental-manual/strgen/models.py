"""Domain model: SharedBlocks (reusable content) vs Properties (specific data).

Design contract
---------------
* A ``SharedBlock`` holds content shared by many properties (WiFi instructions,
  standard house rules, emergency guidance, appliance guides, local tips, brand).
* A ``Property`` holds only property-specific data: address, access codes,
  photos, floor plan, listing copy — plus *links* to shared blocks and
  *overrides* that win over block content at render time.
* Editing a shared block updates every linked property automatically.
  Property-specific data is NEVER written by a block edit; overrides live in a
  separate namespace and are merged read-only during assembly.

Localized text convention
-------------------------
Any JSON value may be a localized node: ``{"$i18n": {"en": "...", "es": "..."}}``.
Assembly merges these per-language so a property can translate one string in
one language without touching anything else.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

I18N_KEY = "$i18n"

BLOCK_KINDS = (
    "arrival",       # welcome & access instructions
    "wifi",          # network details + connect instructions
    "appliances",    # how-to guides with numbered steps
    "rules",         # house rules
    "recommendations",  # local restaurants/shops/transport/hidden gems
    "emergency",     # numbers, hospital, shut-offs
    "brand",         # operator brand kit (colors, logo, footer)
)

PHOTO_SECTIONS = (
    "cover", "living", "kitchen", "bedroom", "bathroom",
    "exterior", "pool", "dining", "other",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "item"


def new_id(prefix: str, name: str) -> str:
    return f"{slugify(name)[:40]}-{uuid.uuid4().hex[:6]}"


# --------------------------------------------------------------------------
# Localized helpers (pure functions over plain dicts — keeps JSON the truth)
# --------------------------------------------------------------------------

def i18n(*lang_text: tuple[str, str]) -> dict[str, Any]:
    """Build a localized node: i18n(("en","Hi"), ("es","Hola"))."""
    return {I18N_KEY: {lang: text for lang, text in lang_text}}


def is_i18n(value: Any) -> bool:
    return isinstance(value, dict) and I18N_KEY in value


def resolve_text(node: Any, lang: str, base_lang: str = "en") -> str:
    """Resolve a possibly-localized value with graceful fallback chain."""
    if isinstance(node, str):
        return node
    if not is_i18n(node):
        return ""
    values = node[I18N_KEY]
    for candidate in (lang, base_lang, "en"):
        if values.get(candidate):
            return values[candidate]
    return next((v for v in values.values() if v), "")


# --------------------------------------------------------------------------
# Shared blocks
# --------------------------------------------------------------------------

@dataclass
class SharedBlock:
    id: str
    kind: str                      # one of BLOCK_KINDS
    name: str
    description: str = ""
    content: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)
    version: int = 1

    KIND_LABELS = {
        "arrival": "Welcome & Arrival",
        "wifi": "WiFi & Connectivity",
        "appliances": "Appliance Guides",
        "rules": "House Rules",
        "recommendations": "Local Recommendations",
        "emergency": "Emergency & Safety",
        "brand": "Brand Kit",
    }

    def validate(self) -> None:
        if self.kind not in BLOCK_KINDS:
            raise ValueError(
                f"Unknown block kind '{self.kind}'. Valid kinds: {', '.join(BLOCK_KINDS)}"
            )

    def touch(self) -> None:
        self.version += 1
        self.updated_at = now_iso()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "kind": self.kind, "name": self.name,
            "description": self.description, "content": self.content,
            "created_at": self.created_at, "updated_at": self.updated_at,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SharedBlock":
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


@dataclass
class Photo:
    id: str
    section: str = "other"                 # one of PHOTO_SECTIONS
    caption: dict[str, Any] = field(default_factory=dict)   # $i18n node or ""
    local_path: str | None = None          # file on disk (svg/jpg/png)
    url: str | None = None                 # stable SuperDocs image URL
    alt: str = ""

    def validate(self) -> None:
        if self.section not in PHOTO_SECTIONS:
            raise ValueError(f"Unknown photo section '{self.section}'")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "section": self.section, "caption": self.caption,
            "local_path": self.local_path, "url": self.url, "alt": self.alt,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Photo":
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


@dataclass
class FloorRoom:
    """A room rectangle on the schematic floor plan (grid units ~ meters)."""
    name: str                # short label key; rendered via i18n labels when known
    x: float
    y: float
    w: float
    h: float

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "x": self.x, "y": self.y, "w": self.w, "h": self.h}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "FloorRoom":
        return cls(d["name"], float(d["x"]), float(d["y"]), float(d["w"]), float(d["h"]))


@dataclass
class Property:
    """A rental unit. Holds ONLY property-specific facts + links/overrides."""
    id: str
    name: str
    tagline: dict[str, Any] = field(default_factory=dict)      # $i18n
    address_lines: list[str] = field(default_factory=list)
    contact_name: str = ""
    contact_phone: str = ""
    contact_email: str = ""
    paper_size: str = "A4"                                      # A4 | Letter
    base_lang: str = "en"
    languages: list[str] = field(default_factory=lambda: ["en"])

    links: dict[str, str] = field(default_factory=dict)         # kind -> block_id
    overrides: dict[str, dict[str, Any]] = field(default_factory=dict)  # kind -> partial content

    photos: list[Photo] = field(default_factory=list)
    floorplan: list[FloorRoom] = field(default_factory=list)
    floorplan_note: dict[str, Any] = field(default_factory=dict)

    listing: dict[str, Any] = field(default_factory=dict)       # selling points etc.
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)

    # -- link management ---------------------------------------------------

    def link_block(self, kind: str, block_id: str) -> None:
        if kind not in BLOCK_KINDS:
            raise ValueError(f"Unknown block kind '{kind}'")
        self.links[kind] = block_id
        self.touch()

    def unlink_block(self, kind: str) -> None:
        self.links.pop(kind, None)
        self.touch()

    def set_override(self, kind: str, partial: dict[str, Any]) -> None:
        """Merge a *partial* override into this property's own namespace.

        Never mutates shared blocks; never deletes existing keys unless the
        caller explicitly passes ``None`` as the new value.
        """
        current = self.overrides.setdefault(kind, {})
        _deep_merge(current, partial)
        self.touch()

    def clear_override(self, kind: str, key_path: str | None = None) -> None:
        if kind not in self.overrides:
            return
        if key_path is None:
            del self.overrides[kind]
        else:
            node = self.overrides[kind]
            parts = key_path.split(".")
            for part in parts[:-1]:
                node = node[part]  # KeyError -> caller's problem, surfaced loudly
            node.pop(parts[-1], None)
            if not self.overrides[kind]:
                del self.overrides[kind]
        self.touch()

    def touch(self) -> None:
        self.updated_at = now_iso()

    # -- serialization -----------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "name": self.name, "tagline": self.tagline,
            "address_lines": self.address_lines,
            "contact_name": self.contact_name, "contact_phone": self.contact_phone,
            "contact_email": self.contact_email,
            "paper_size": self.paper_size, "base_lang": self.base_lang,
            "languages": self.languages,
            "links": self.links, "overrides": self.overrides,
            "photos": [p.to_dict() for p in self.photos],
            "floorplan": [r.to_dict() for r in self.floorplan],
            "floorplan_note": self.floorplan_note,
            "listing": self.listing,
            "created_at": self.created_at, "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Property":
        prop = cls(**{k: v for k, v in d.items()
                      if k in {"id", "name", "tagline", "address_lines", "contact_name",
                               "contact_phone", "contact_email", "paper_size", "base_lang",
                               "languages", "links", "overrides", "listing",
                               "floorplan_note", "created_at", "updated_at"}})
        prop.photos = [Photo.from_dict(p) for p in d.get("photos", [])]
        prop.floorplan = [FloorRoom.from_dict(r) for r in d.get("floorplan", [])]
        return prop


# --------------------------------------------------------------------------
# Deep merge used by assembly (and only there — single source of truth)
# --------------------------------------------------------------------------

def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge ``override`` into ``base`` (mutates base).

    Rules:
      dict  + dict   -> recursive merge
      $i18n + $i18n  -> per-language merge (partial translations allowed)
      list + any     -> override replaces entirely (predictable semantics)
      scalar + any   -> override wins
    """
    for key, value in override.items():
        if value is None:
            base[key] = None
        elif is_i18n(value) and is_i18n(base.get(key)):
            langs = base[key][I18N_KEY]
            for lang, text in value[I18N_KEY].items():
                langs[lang] = text
        elif isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base
