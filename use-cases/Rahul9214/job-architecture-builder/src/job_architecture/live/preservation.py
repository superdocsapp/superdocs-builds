"""Preservation checks against exported DOCX text, not container bytes."""

from __future__ import annotations

import re
import zipfile
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass
from html import unescape
from pathlib import Path
from typing import Mapping

W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


@dataclass(frozen=True)
class DocxLayoutSummary:
    paragraph_count: int
    run_count: int
    break_count: int
    level_expectations_paragraphs: int
    level_expectations_runs: int
    level_expectations_breaks: int
    text: str

    def as_dict(self) -> dict[str, int]:
        return {
            "paragraph_count": self.paragraph_count,
            "run_count": self.run_count,
            "break_count": self.break_count,
            "level_expectations_paragraphs": self.level_expectations_paragraphs,
            "level_expectations_runs": self.level_expectations_runs,
            "level_expectations_breaks": self.level_expectations_breaks,
        }


@dataclass(frozen=True)
class ExportPreservationCheck:
    found_new_fragment: bool
    preserved_markers: tuple[str, ...]
    missing_markers: tuple[str, ...]
    excerpt: str

    @property
    def ok(self) -> bool:
        return self.found_new_fragment and not self.missing_markers


@dataclass(frozen=True)
class FrameworkExportCheck:
    found_markers: tuple[str, ...]
    missing_markers: tuple[str, ...]
    looks_like_source_jd: bool
    excerpt: str

    @property
    def ok(self) -> bool:
        return not self.missing_markers and not self.looks_like_source_jd


def _heading(name: str) -> re.Pattern[str]:
    return re.compile(rf"(?im)^(?:#+\s*)?{name}\b")


def _word(label: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![A-Za-z0-9]){re.escape(label)}(?![A-Za-z0-9])")


FRAMEWORK_EXPORT_MARKERS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("purpose", _heading("purpose")),
    ("principles", _heading("principles")),
    ("individual_contributor_track", re.compile(r"individual\s+contributor", re.I)),
    ("people_manager_track", re.compile(r"people\s+manager", re.I)),
    ("IC1", _word("IC1")),
    ("IC2", _word("IC2")),
    ("IC3", _word("IC3")),
    ("IC4", _word("IC4")),
    ("IC5", _word("IC5")),
    ("M1", _word("M1")),
    ("M2", _word("M2")),
    ("M3", _word("M3")),
    ("job_family", re.compile(r"job\s+famil(?:y|ies)", re.I)),
)


def extract_docx_text(path: Path) -> str:
    return inspect_docx_layout(path).text


def inspect_docx_layout(path: Path) -> DocxLayoutSummary:
    """Read WordprocessingML layout. Line breaks (`w:br`) are semantic newlines, not missing fields."""
    with zipfile.ZipFile(path) as archive:
        xml = archive.read("word/document.xml")
    root = ElementTree.fromstring(xml)
    paragraphs: list[str] = []
    run_count = 0
    break_count = 0
    in_level = False
    level_paragraphs = 0
    level_runs = 0
    level_breaks = 0
    for paragraph in root.iter(f"{W_NS}p"):
        text, runs, breaks = _paragraph_plain_text(paragraph)
        run_count += runs
        break_count += breaks
        heading = text.strip().lower()
        if heading == "level expectations":
            in_level = True
            if text.strip():
                paragraphs.append(text.strip())
            continue
        if in_level and heading in {
            "progression",
            "source / evidence note",
            "role purpose",
            "responsibilities",
            "scope / decision making",
            "core competencies",
        }:
            in_level = False
        if in_level and text.strip():
            level_paragraphs += 1
            level_runs += runs
            level_breaks += breaks
        if text.strip():
            paragraphs.append(text.strip())
    return DocxLayoutSummary(
        paragraph_count=len(list(root.iter(f"{W_NS}p"))),
        run_count=run_count,
        break_count=break_count,
        level_expectations_paragraphs=level_paragraphs,
        level_expectations_runs=level_runs,
        level_expectations_breaks=level_breaks,
        text="\n".join(paragraphs),
    )


def _paragraph_plain_text(paragraph: ElementTree.Element) -> tuple[str, int, int]:
    chunks: list[str] = []
    runs = 0
    breaks = 0
    for node in paragraph.iter():
        if node.tag == f"{W_NS}r":
            runs += 1
        elif node.tag == f"{W_NS}t" and node.text:
            chunks.append(node.text)
        elif node.tag in {f"{W_NS}br", f"{W_NS}cr"}:
            chunks.append("\n")
            breaks += 1
        elif node.tag == f"{W_NS}tab":
            chunks.append("\t")
    return "".join(chunks).strip(), runs, breaks


def verify_exported_profile(
    path: Path,
    *,
    expected_new_fragment: str,
    preserved_markers: Mapping[str, str],
) -> ExportPreservationCheck:
    text = extract_docx_text(path)
    lowered = text.lower()
    missing = tuple(
        name for name, marker in preserved_markers.items() if marker.lower() not in lowered
    )
    return ExportPreservationCheck(
        found_new_fragment=expected_new_fragment.lower() in lowered,
        preserved_markers=tuple(preserved_markers),
        missing_markers=missing,
        excerpt=text[:2000],
    )


def visible_export_text(value: str) -> str:
    """Normalize HTML or plain text so heading/label checks share one path."""
    if "<" not in value or ">" not in value:
        return value
    text = re.sub(r"(?i)<br\s*/?>", "\n", value)
    text = re.sub(r"(?i)<h[1-6][^>]*>", "\n", text)
    text = re.sub(r"(?i)</h[1-6]>", "\n", text)
    text = re.sub(r"(?i)</(p|li|tr|div)>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    return unescape(text)


def verify_framework_content(text: str) -> FrameworkExportCheck:
    """Semantic check on rendered framework HTML or extracted DOCX text."""
    visible = visible_export_text(text)
    found: list[str] = []
    missing: list[str] = []
    for name, pattern in FRAMEWORK_EXPORT_MARKERS:
        if pattern.search(visible):
            found.append(name)
        else:
            missing.append(name)
    lowered = visible.lower()
    looks_like_jd = "role purpose" in lowered or lowered.lstrip().startswith(
        "software engineer"
    )
    return FrameworkExportCheck(
        found_markers=tuple(found),
        missing_markers=tuple(missing),
        looks_like_source_jd=looks_like_jd,
        excerpt=visible[:2000],
    )


def verify_exported_framework(path: Path) -> FrameworkExportCheck:
    """Semantic check that a DOCX is a job-architecture framework, not a source JD.

    File existence is not success. Byte identity is not required. An ordinary
    job description (for example a Software Engineer Backend JD) must fail.
    """
    return verify_framework_content(extract_docx_text(path))
