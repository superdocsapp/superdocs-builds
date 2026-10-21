"""Step 2: text and table extraction.

Document text is read as inert data. It is never interpolated into a system
or instruction prompt by any function in this module or elsewhere in the
package — extraction and rules only ever *read* contract text as a value.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from typing import Optional


def extract_document_text(file_path: str) -> str:
    """Read raw text from a corpus document. No parsing of structure here."""

    with open(file_path, "r", encoding="utf-8") as handle:
        return handle.read()


@dataclass(frozen=True)
class CsvRow:
    values: dict[str, str]


def extract_csv_table(text: str) -> list[CsvRow]:
    """Parse a CSV-formatted rate card into rows of raw string values."""

    reader = csv.DictReader(io.StringIO(text))
    return [CsvRow(values=dict(row)) for row in reader]


def find_span(text: str, needle: str) -> Optional[tuple[int, int]]:
    """Locate a verbatim substring in text, returning (start, end) offsets.

    Whitespace-normalized fallback is attempted if an exact match fails,
    since source contracts use Markdown emphasis markers (`**`) inline with
    the numbers being quoted.
    """

    idx = text.find(needle)
    if idx != -1:
        return idx, idx + len(needle)

    def normalize(s: str) -> str:
        return " ".join(s.replace("**", "").split())

    normalized_text = normalize(text)
    normalized_needle = normalize(needle)
    idx = normalized_text.find(normalized_needle)
    if idx == -1:
        return None
    return idx, idx + len(normalized_needle)


def section_for_offset(text: str, offset: int) -> Optional[str]:
    """Best-effort: return the nearest preceding heading/section marker."""

    preceding = text[:offset]
    lines = preceding.splitlines()
    for line in reversed(lines):
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()
        if stripped.upper().startswith("SECTION"):
            return stripped
        if stripped.upper().startswith("ARTICLE"):
            return stripped
        if stripped.upper().startswith("CLAUSE"):
            return stripped
        if stripped.startswith("§"):
            return stripped
    return None
