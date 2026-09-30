"""Did the text actually leave the file? Measured on the bytes handed over —
never claimed on trust.

A `.docx` is a zip, and the same sentence can sit outside `word/document.xml`:

    word/comments.xml            a reviewer's comment quoting it
    word/document.xml            inside <w:del> — a tracked deletion keeps its text
    word/footnotes.xml           }
    word/endnotes.xml            } separate parts entirely
    word/header*.xml             }
    docProps/core.xml            title, author, keywords, last-modified-by
    docProps/app.xml, custom.xml company, and whatever was added

We search every part and report per part, so the audit distinguishes "removed"
from "removed from the place you were looking". `docProps/*` is outside the
redaction pipeline, so it is checked and *reported*, never claimed as cleaned.

See extensions/redaction-pane/README.md § "The clean copy".
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from io import BytesIO

PROPERTY_PARTS = ("docProps/core.xml", "docProps/app.xml", "docProps/custom.xml")
"""Outside the redaction pipeline. Checked, reported, never claimed as cleaned."""

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
_MARKER = re.compile(r"\[(?:[A-Z][A-Z ]*)?REDACTED\]")
"""Any typed marker — `[SSN REDACTED]`, `[CREDIT CARD REDACTED]`, or the bare
`[REDACTED]`. Matching only a fixed `[REDACTED]` reported zero markers on a
correctly redacted file, which `Report.summary` reads as "nothing applied". The
bare form still counts — older documents and the test fixture carry it."""


@dataclass(frozen=True, slots=True)
class Residue:
    """One string that survived, and where."""

    text: str
    part: str
    in_document_properties: bool


@dataclass
class Report:
    """What the export actually contains."""

    clean: bool
    """True only when no confirmed string appears in any part of the package
    **outside** document properties. Property residue is reported separately
    because removing it is not something this pane does."""
    residue: list[Residue] = field(default_factory=list)
    property_residue: list[Residue] = field(default_factory=list)
    parts_checked: int = 0
    markers_found: int = 0
    """Markers of any type found. No residue AND no markers usually means nothing
    was applied — a distinction the pane needs before it says the job is done."""

    @property
    def summary(self) -> str:
        if self.clean and not self.property_residue:
            return (
                f"{self.markers_found} redaction markers, and no redacted text found "
                f"in any of the {self.parts_checked} parts of the file."
            )
        if self.clean:
            names = ", ".join(sorted({item.part for item in self.property_residue}))
            return (
                f"Removed from the document ({self.markers_found} markers, "
                f"{self.parts_checked} parts checked), but still present in {names} — "
                "document properties are outside what this pane removes."
            )
        where = ", ".join(sorted({item.part for item in self.residue}))
        return f"{len(self.residue)} redacted string(s) still present in {where}."


def _flatten(xml: bytes) -> str:
    """XML → the text a search must match. Tags are dropped, not parsed: Word
    splits a string across runs (`<w:t>123-45</w:t><w:t>-6789</w:t>`), and a
    check that missed that would pass a file still carrying the number."""
    return _WS.sub(" ", _TAG.sub("", xml.decode("utf-8", errors="ignore")))


def check(package: bytes, removed: list[str]) -> Report:
    """Search every part of the .docx for every string that was redacted."""
    report = Report(clean=True)
    wanted = [text for text in {t.strip() for t in removed} if len(text) >= 3]

    with zipfile.ZipFile(BytesIO(package)) as archive:
        for name in archive.namelist():
            if not name.endswith((".xml", ".rels")):
                continue
            report.parts_checked += 1
            flat = _flatten(archive.read(name))
            report.markers_found += len(_MARKER.findall(flat))

            for text in wanted:
                if text in flat or _WS.sub(" ", text) in flat:
                    hit = Residue(
                        text=text,
                        part=name,
                        in_document_properties=name in PROPERTY_PARTS,
                    )
                    if hit.in_document_properties:
                        report.property_residue.append(hit)
                    else:
                        report.residue.append(hit)
                        report.clean = False
    return report
