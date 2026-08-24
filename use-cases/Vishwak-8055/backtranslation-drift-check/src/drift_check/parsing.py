"""Deterministic document parsing and section identification.

Supported input shape (deliberately simple — see LIMITATIONS.md):

    # Document Title
    <optional preamble text>

    ## First Section Heading
    Body text for the first section, one or more paragraphs.

    ## Second Section Heading
    Body text for the second section.

Section boundaries are ``##`` (level-2) headings only; deeper headings are
treated as part of the enclosing section's body. This is a scope boundary,
not an oversight — see LIMITATIONS.md #1.

Section IDs are built from the 1-based order plus a slug of the heading text
(``S3-operating-temperature-restriction``), so they are stable across reruns
of the *same* document and readable in reports. Because slugs are cosmetic,
every downstream lookup that needs a guaranteed-stable key (fixtures, caches)
uses ``Section.index`` instead of ``Section.id`` — see DECISIONS.md #2.
"""

from __future__ import annotations

import re
import unicodedata

from drift_check.integrity import sha256_hex
from drift_check.models import Document, Section

_HEADING_RE = re.compile(r"^##\s+(.*\S)\s*$")
_TITLE_RE = re.compile(r"^#\s+(.*\S)\s*$")


class DocumentParseError(ValueError):
    """Raised for structurally invalid input the parser cannot safely recover from."""


def slugify(text: str, max_len: int = 40) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    ascii_only = ascii_only.lower()
    ascii_only = re.sub(r"[^a-z0-9]+", "-", ascii_only).strip("-")
    if not ascii_only:
        ascii_only = "section"
    return ascii_only[:max_len].strip("-")


def _normalize_text(raw_text: str) -> str:
    # NFC normalization so visually-identical strings with different Unicode
    # composition (e.g. combining accents vs. precomposed) hash and compare
    # equal, per the "unexpected Unicode" robustness requirement.
    text = unicodedata.normalize("NFC", raw_text)
    # Normalize line endings; do not otherwise alter whitespace, since
    # whitespace-only edits are still edits and section hashes should be
    # sensitive to them for integrity purposes.
    return text.replace("\r\n", "\n").replace("\r", "\n")


def parse_document(raw_text: str, *, document_id: str, language: str) -> Document:
    """Parse raw markdown-like text into a Document with ordered Sections.

    An empty document (no ``##`` headings found) is not an error: it parses
    to zero sections. Downstream alignment treats a zero-section document as
    review-required rather than the parser raising, so that a genuinely empty
    upload produces an auditable finding instead of a crash.
    """
    text = _normalize_text(raw_text)
    lines = text.split("\n")

    title = document_id
    body_start = 0
    for i, line in enumerate(lines):
        m = _TITLE_RE.match(line)
        if m:
            title = m.group(1).strip()
            body_start = i + 1
            break
        if line.strip():
            # First non-blank line isn't a title line; stop looking.
            break

    sections: list[Section] = []
    seen_slugs: dict[str, int] = {}
    current_heading: str | None = None
    current_body: list[str] = []

    def flush() -> None:
        if current_heading is None:
            return
        heading = current_heading.strip()
        body = "\n".join(current_body).strip("\n")
        slug = slugify(heading)
        seen_slugs[slug] = seen_slugs.get(slug, 0) + 1
        suffix = "" if seen_slugs[slug] == 1 else f"-{seen_slugs[slug]}"
        section_id = f"S{len(sections) + 1}-{slug}{suffix}"
        sections.append(
            Section(
                id=section_id,
                index=len(sections) + 1,
                heading=heading,
                text=body,
                content_hash=sha256_hex(f"{heading}\u241f{body}"),
            )
        )

    for line in lines[body_start:]:
        m = _HEADING_RE.match(line)
        if m:
            flush()
            current_heading = m.group(1)
            current_body = []
        else:
            if current_heading is not None:
                current_body.append(line)
            # Text before the first heading (besides the title) is treated as
            # front matter and intentionally dropped from sectioning — it is
            # still part of raw_text and therefore still covered by the
            # whole-document integrity hash.
    flush()

    return Document(
        id=document_id,
        language=language,
        title=title,
        sections=tuple(sections),
        raw_text=raw_text,
        source_hash=sha256_hex(raw_text),
    )
