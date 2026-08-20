"""Required-section presence checks.

If the AI drops a required field, comparability across debriefs/quarters breaks
silently unless something catches it. This module is that something. It is pure
HTML parsing -- no network, no LLM call, fully unit-testable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup

from .templates import (
    BRIEF_SECTION_HEADINGS,
    DEBRIEF_SECTION_HEADINGS,
    REQUIRED_BRIEF_SECTIONS,
    REQUIRED_DEBRIEF_SECTIONS,
)


def _normalize_heading(heading: str) -> str:
    """Normalize heading text for schema comparison.

    Generated documents may prefix required headings with section numbers,
    e.g. "1. Overview & Methodology". Numbering is presentation-only and
    should not affect schema validation.
    """
    heading = re.sub(r"^\s*\d+\.\s*", "", heading)
    return heading.strip().lower()


@dataclass
class SchemaCheckResult:
    ok: bool
    missing_sections: list[str] = field(default_factory=list)
    found_headings: list[str] = field(default_factory=list)

    def raise_if_failed(self, document_label: str) -> None:
        if not self.ok:
            raise SchemaValidationError(
                f"{document_label} is missing required section(s): "
                f"{', '.join(self.missing_sections)}. Found headings: "
                f"{', '.join(self.found_headings) or '(none)'}."
            )


class SchemaValidationError(RuntimeError):
    pass


def _extract_h2_headings(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    return [h2.get_text(strip=True) for h2 in soup.find_all("h2")]


def check_sections(
    html: str,
    required_keys: list[str],
    heading_map: dict[str, str],
) -> SchemaCheckResult:
    found = _extract_h2_headings(html)

    found_normalized = {_normalize_heading(h) for h in found}

    missing = [
        heading_map[key]
        for key in required_keys
        if _normalize_heading(heading_map[key]) not in found_normalized
    ]

    return SchemaCheckResult(
        ok=not missing,
        missing_sections=missing,
        found_headings=found,
    )


def check_debrief_schema(html: str) -> SchemaCheckResult:
    return check_sections(
        html,
        REQUIRED_DEBRIEF_SECTIONS,
        DEBRIEF_SECTION_HEADINGS,
    )


def check_brief_schema(html: str) -> SchemaCheckResult:
    return check_sections(
        html,
        REQUIRED_BRIEF_SECTIONS,
        BRIEF_SECTION_HEADINGS,
    )