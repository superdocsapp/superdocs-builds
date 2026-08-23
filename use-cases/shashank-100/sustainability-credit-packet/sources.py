"""Prepare source files for upload.

The upload endpoint accepts .docx, .htm, .html, .md, .pdf, .rtf, .tex and .txt
-- but not .csv. Tabular evidence is real and common in this domain (fixture
schedules, hauler logs, occupancy assumptions), so rather than dropping it we
render it to Markdown, which the endpoint does accept.

The rendering is faithful and lossless for the shapes we handle: every row and
column survives, so the narrative is still written against the real evidence
rather than a summary of it. The rendered file is written next to a cache so
repeated runs do not redo the work.
"""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path

UPLOADABLE = {".docx", ".htm", ".html", ".md", ".pdf", ".rtf", ".tex", ".txt"}
CONVERTIBLE = {".csv"}


class UnsupportedSource(ValueError):
    """A source file the API cannot take and we cannot convert."""


def _escape(cell: str) -> str:
    return cell.replace("|", "\\|").strip()


def csv_to_markdown(path: Path, *, max_rows: int | None = None) -> str:
    """Render a CSV as a Markdown table, preserving every value."""
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    if not rows:
        return f"# {path.name}\n\n(empty file)\n"

    header, body = rows[0], rows[1:]
    truncated = max_rows is not None and len(body) > max_rows
    shown = body[:max_rows] if truncated else body

    lines = [
        f"# {path.name}",
        "",
        f"Source data file, {len(body)} rows. Rendered from CSV for upload.",
        "",
        "| " + " | ".join(_escape(c) for c in header) + " |",
        "|" + "|".join(["---"] * len(header)) + "|",
    ]
    for row in shown:
        padded = row + [""] * (len(header) - len(row))
        lines.append("| " + " | ".join(_escape(c) for c in padded[: len(header)]) + " |")

    if truncated:
        lines.append("")
        lines.append(f"({len(body) - max_rows} further rows not shown)")
    return "\n".join(lines) + "\n"


def prepare(path: Path, cache_dir: Path) -> Path:
    """Return a path the upload endpoint will accept.

    Files already in an accepted format are returned unchanged. Convertible
    ones are rendered into the cache directory, keyed by content hash so a
    changed source produces a fresh render rather than a stale one.
    """
    path = Path(path)
    suffix = path.suffix.lower()

    if suffix in UPLOADABLE:
        return path
    if suffix not in CONVERTIBLE:
        raise UnsupportedSource(
            f"{path.name}: .{suffix.lstrip('.')} cannot be uploaded and has no converter. "
            f"Accepted directly: {', '.join(sorted(UPLOADABLE))}"
        )

    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    rendered = cache_dir / f"{path.stem}-{digest}.md"

    if not rendered.exists():
        rendered.write_text(csv_to_markdown(path), encoding="utf-8")
    return rendered
