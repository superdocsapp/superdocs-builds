"""Deterministic extraction of manuscript headings from supplied instructions."""

from __future__ import annotations

import re


class TemplateStructureError(ValueError):
    """Raised when supplied template information does not establish a structure."""


_STRUCTURE_MARKER = re.compile(
    r"^(?:required\s+)?(?:manuscript\s+)?(?:sections|structure|headings)\s*:\s*(.*)$",
    re.IGNORECASE,
)
_LIST_PREFIX = re.compile(
    r"^\s*(?:#{1,6}\s+|[-*\u2022]\s+|\(?(?:\d+|[ivxlcdm]+)\)?[.)]\s+)",
    re.IGNORECASE,
)
_METADATA_LINE = re.compile(
    r"^(?:target\s+)?journal(?:\s+name)?\s*:", re.IGNORECASE
)
_STOP_MARKER = re.compile(
    r"^(?:notes?|instructions?|requirements?|formatting)\s*:", re.IGNORECASE
)


def _clean_heading(value: str) -> str:
    value = _LIST_PREFIX.sub("", value.strip())
    value = value.strip(" \t#*_`[]")
    return re.sub(r"\s+", " ", value).strip()


def _split_inline_headings(value: str) -> list[str]:
    return [
        cleaned
        for part in re.split(r"\s*(?:,|;|\||->|>)\s*", value)
        if (cleaned := _clean_heading(part))
    ]


def _looks_like_plain_heading(value: str) -> bool:
    cleaned = _clean_heading(value)
    return (
        bool(cleaned)
        and len(cleaned) <= 80
        and len(cleaned.split()) <= 10
        and not cleaned.endswith((".", "?", "!"))
        and not _METADATA_LINE.match(cleaned)
    )


class JournalTemplateParser:
    """Parse only structures explicitly present in user-supplied template text."""

    def extract_sections(self, template_information: str) -> tuple[str, ...]:
        lines = [line.strip() for line in template_information.splitlines() if line.strip()]
        candidates: list[str] = []
        inside_structure = False

        for line in lines:
            marker = _STRUCTURE_MARKER.match(line)
            if marker:
                inside_structure = True
                if marker.group(1):
                    candidates.extend(_split_inline_headings(marker.group(1)))
                continue

            if inside_structure and _STOP_MARKER.match(line):
                inside_structure = False
                continue

            if _LIST_PREFIX.match(line):
                candidates.append(_clean_heading(line))
                continue

            if inside_structure and _looks_like_plain_heading(line):
                candidates.append(_clean_heading(line))

        if not candidates and len(lines) >= 2 and all(
            _looks_like_plain_heading(line) for line in lines
        ):
            candidates = [_clean_heading(line) for line in lines]

        unique: list[str] = []
        seen: set[str] = set()
        for heading in candidates:
            key = heading.casefold()
            if heading and key not in seen:
                unique.append(heading)
                seen.add(key)

        if len(unique) < 2:
            raise TemplateStructureError(
                "The supplied journal/template information does not contain at least "
                "two explicit manuscript headings. Use a 'Required sections:' list, "
                "a numbered list, bullets, or Markdown headings."
            )

        return tuple(unique)
