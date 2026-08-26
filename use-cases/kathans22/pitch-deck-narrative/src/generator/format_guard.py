"""Assertions that an export cannot be confused with a slide file.

Structural enforcement of the Build 2 card constraint — not a prose reminder.
"""

from __future__ import annotations

import re
from pathlib import Path

# Substrings forbidden in filenames and titles (case-insensitive).
_FORBIDDEN_NAME_TOKENS = (
    "deck",
    "slides",
    "slide-deck",
    "presentation",
    "powerpoint",
    "keynote",
)

# Extensions that imply a slide-producing surface. SuperDocs has none of these
# for this build; rejecting them is defence in depth.
_FORBIDDEN_EXTENSIONS = (
    ".pptx",
    ".ppt",
    ".ppsx",
    ".pps",
    ".odp",
    ".key",
)

_ALLOWED_DOCUMENT_EXTENSIONS = (
    ".md",
    ".markdown",
    ".docx",
    ".pdf",
    ".html",
    ".htm",
    ".txt",
)

_ALLOWED_EXPORT_FORMATS = frozenset(
    {"markdown", "md", "docx", "pdf", "html", "txt", "doc"}
)


class FormatGuardError(ValueError):
    """Raised when an export fails a format-guard check. Message names the check."""


def _lower(text: str) -> str:
    return (text or "").lower()


def assert_filename_not_deck(exported_path: str | Path) -> None:
    """Filename must not carry deck/slide/presentation signatures or slide extensions."""
    path = Path(exported_path)
    name = path.name
    stem = path.stem
    suffix = path.suffix.lower()

    if suffix in _FORBIDDEN_EXTENSIONS:
        raise FormatGuardError(
            f"format_guard.filename: refused slide-adjacent extension {suffix!r} "
            f"on {name!r}. Fix: export as .docx/.md (speaking script), never a "
            "presentation file."
        )
    if suffix and suffix not in _ALLOWED_DOCUMENT_EXTENSIONS:
        raise FormatGuardError(
            f"format_guard.filename: unsupported export extension {suffix!r} on "
            f"{name!r}. Fix: use a document format "
            f"({', '.join(_ALLOWED_DOCUMENT_EXTENSIONS)})."
        )

    haystack = _lower(f"{stem} {name}")
    for token in _FORBIDDEN_NAME_TOKENS:
        # Allow the word "slide-equivalent" in body, but not in the filename.
        if token in haystack:
            raise FormatGuardError(
                f"format_guard.filename: {name!r} contains forbidden token "
                f"{token!r}. Fix: name exports pitch-script-<vertical>-<product>."
            )


def assert_title_not_deck(title: str) -> None:
    """Document title must not read as a deck / slides / presentation."""
    haystack = _lower(title)
    if not haystack.strip():
        raise FormatGuardError(
            "format_guard.title: title is empty. Fix: pass the document H1 / title "
            "that names a speaking script."
        )
    for token in _FORBIDDEN_NAME_TOKENS:
        if token in haystack:
            raise FormatGuardError(
                f"format_guard.title: title {title!r} contains forbidden token "
                f"{token!r}. Fix: title must name a speaking script, not a deck."
            )


# Canonical first-section disclaimer (must appear in the exported document).
SPEAKING_SCRIPT_DISCLAIMER = "Speaking script — not a slide deck."

_DASH_RE = re.compile(r"[\u2010-\u2015\u2212\-]+")
_SPACE_RE = re.compile(r"\s+")


def _normalize_disclaimer_text(text: str) -> str:
    """Collapse dash/whitespace variants so em-dash vs hyphen still match."""
    lowered = _lower(text)
    collapsed = _DASH_RE.sub("-", lowered)
    return _SPACE_RE.sub(" ", collapsed).strip()


def _read_document_prefix(exported_path: str | Path, max_chars: int = 4000) -> str:
    """Read the start of an exported document for disclaimer scanning."""
    path = Path(exported_path)
    suffix = path.suffix.lower()
    if suffix in {".md", ".markdown", ".txt", ".html", ".htm"}:
        return path.read_text(encoding="utf-8", errors="replace")[:max_chars]
    if suffix == ".docx":
        import zipfile
        from xml.etree import ElementTree as ET

        with zipfile.ZipFile(path) as zf:
            xml_bytes = zf.read("word/document.xml")
        root = ET.fromstring(xml_bytes)
        texts: list[str] = []
        for node in root.iter():
            if node.tag.endswith("}t") and node.text:
                texts.append(node.text)
            if sum(len(t) for t in texts) >= max_chars:
                break
        return " ".join(texts)[:max_chars]
    # Binary/unknown: best-effort decode of a short prefix.
    return path.read_bytes()[:max_chars].decode("utf-8", errors="replace")


def assert_speaking_script_disclaimer(exported_path: str | Path) -> None:
    """First section must plainly state this is a speaking script, not a slide deck.

    Checks the exported file itself — writing the line once in the skeleton is not
    enough; the guard re-reads the export and fails if the string is missing.
    """
    path = Path(exported_path)
    if not path.is_file():
        raise FormatGuardError(
            f"format_guard.disclaimer: export file missing at {path}. Fix: export "
            "before asserting."
        )
    prefix = _read_document_prefix(path)
    needle = _normalize_disclaimer_text(SPEAKING_SCRIPT_DISCLAIMER)
    haystack = _normalize_disclaimer_text(prefix)
    if needle not in haystack:
        raise FormatGuardError(
            "format_guard.disclaimer: speaking-script disclaimer line is missing "
            f"from the start of {path.name}. Expected a line equivalent to "
            f"{SPEAKING_SCRIPT_DISCLAIMER!r}. Fix: ensure the skeleton notice "
            "survives fill+export; do not strip it in chat edits."
        )


def assert_document_export_path(export_format: str | None) -> None:
    """Defence in depth: only document export formats are allowed (never slides).

    SuperDocs has no slide-producing surface in this build; this still rejects any
    caller that tries to pass a presentation format through the export path.
    """
    fmt = _lower(export_format or "").strip()
    if not fmt:
        raise FormatGuardError(
            "format_guard.export_path: export_format is missing. Fix: pass a "
            "document format (markdown/docx/pdf/html/txt)."
        )
    if fmt in {"pptx", "ppt", "ppsx", "pps", "odp", "key", "presentation", "slides"}:
        raise FormatGuardError(
            f"format_guard.export_path: refused slide/presentation format {fmt!r}. "
            "Fix: this build only exports speaking-script documents via "
            "document export (markdown/docx)."
        )
    if fmt not in _ALLOWED_EXPORT_FORMATS:
        raise FormatGuardError(
            f"format_guard.export_path: unknown export format {fmt!r}. Fix: use one "
            f"of {sorted(_ALLOWED_EXPORT_FORMATS)}."
        )


def extract_document_title(exported_path: str | Path, fallback: str = "") -> str:
    """Best-effort title from markdown H1 or the provided fallback."""
    path = Path(exported_path)
    if path.suffix.lower() in {".md", ".markdown", ".html", ".htm", ".txt"}:
        text = path.read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("# "):
                return stripped.lstrip("#").strip()
            if stripped.lower().startswith("<h1"):
                return re.sub(r"<[^>]+>", "", stripped).strip()
    return fallback


def assert_not_deck(
    exported_path: str | Path,
    title: str,
    *,
    export_format: str | None = None,
) -> None:
    """Block any export that looks like a slide deck.

    Runs structural checks in order and names the failed check in FormatGuardError:
      1. format_guard.export_path
      2. format_guard.filename
      3. format_guard.title
      4. format_guard.disclaimer
    """
    path = Path(exported_path)
    # Infer format from path when caller omits it (still validates extension).
    inferred = export_format
    if inferred is None:
        suffix = path.suffix.lower().lstrip(".")
        if suffix == "markdown":
            inferred = "markdown"
        elif suffix == "md":
            inferred = "markdown"
        else:
            inferred = suffix or None

    assert_document_export_path(inferred)
    assert_filename_not_deck(path)
    resolved_title = (title or "").strip() or extract_document_title(path)
    assert_title_not_deck(resolved_title)
    assert_speaking_script_disclaimer(path)
