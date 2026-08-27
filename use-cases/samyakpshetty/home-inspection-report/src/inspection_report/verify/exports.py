"""Reading an exported report back, and holding it to what was promised.

The card asks for one thing to be confirmed: that the exported report groups everything
correctly by system. This module is that confirmation, and it works the only way a
confirmation is worth anything — by opening the finished file and reading it, rather than by
inspecting the HTML that was sent and assuming the rest.

It runs against both the offline and the live path, because both produce real files.
"""

from __future__ import annotations

import bisect
import html as html_lib
import io
import re
import zipfile
from dataclasses import dataclass, field

from inspection_report.domain import catalogue
from inspection_report.domain.models import Inspection
from inspection_report.phrasing import rail


@dataclass
class Check:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class VerificationReport:
    """What the finished file actually contains."""

    fmt: str
    checks: list[Check] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)

    def add(self, name: str, passed: bool, detail: str = "") -> None:
        self.checks.append(Check(name, passed, detail))

    def render(self) -> str:
        lines = [f"  {self.fmt.upper()}"]
        for c in self.checks:
            mark = "PASS" if c.passed else "FAIL"
            lines.append(f"    [{mark}] {c.name}{f' — {c.detail}' if c.detail else ''}")
        return "\n".join(lines)


def text_of_docx(data: bytes) -> str:
    """All paragraph text, in document order, straight out of the OOXML.

    Entities are unescaped: a system called "Heating & Cooling" is stored as
    ``Heating &amp; Cooling``, and comparing against the raw form would report a heading as
    missing when it is plainly there.
    """
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        xml = z.read("word/document.xml").decode("utf-8", "replace")
    paragraphs = re.findall(r"<w:p[ >].*?</w:p>", xml, re.DOTALL)
    out = []
    for p in paragraphs:
        runs = re.findall(r"<w:t[^>]*>(.*?)</w:t>", p, re.DOTALL)
        line = "".join(runs).strip()
        if line:
            out.append(html_lib.unescape(re.sub(r"<[^>]+>", "", line)))
    return "\n".join(out)


def images_in_docx(data: bytes) -> list[str]:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return [n for n in z.namelist() if n.startswith("word/media/")]


def text_of_pdf(data: bytes) -> str:
    import pymupdf as fitz

    doc = fitz.open(stream=data, filetype="pdf")
    try:
        return "\n".join(doc[i].get_text() for i in range(len(doc)))
    finally:
        doc.close()


def images_in_pdf(data: bytes) -> int:
    import pymupdf as fitz

    doc = fitz.open(stream=data, filetype="pdf")
    try:
        return sum(len(doc[i].get_images()) for i in range(len(doc)))
    finally:
        doc.close()


# The verification travels back as an HTTP header, and a header has a ceiling. A long report
# whose author writes freely could otherwise grow one past it and lose the whole response, so
# the list is bounded the way the misplaced-findings check already bounds its own.
_MAX_PHRASES = 6


def _phrases(breaches: list[rail.Breach]) -> str:
    if not breaches:
        return ""
    shown = "; ".join(f"{b.matched!r} ({b.category})" for b in breaches[:_MAX_PHRASES])
    extra = len(breaches) - _MAX_PHRASES
    return f"{shown} and {extra} more" if extra > 0 else shown


def verify(
    *, data: bytes, fmt: str, inspection: Inspection, expect_photos: bool = True
) -> VerificationReport:
    """Hold one exported file to the structure the inspection promised."""
    report = VerificationReport(fmt=fmt)
    text = text_of_docx(data) if fmt == "docx" else text_of_pdf(data)
    # Line-oriented, not one flat string: a system's *heading* is a line of its own, while
    # its name also appears in the "what was inspected" sentence near the top. Searching the
    # flattened text finds that sentence and puts every section boundary in the wrong place.
    lines = [" ".join(ln.split()) for ln in text.splitlines() if ln.strip()]
    flat = " ".join(lines)
    # Offset of each line within `flat`, so a phrase found in the joined text can be mapped
    # back to the line it starts on. Needed because a PDF export wraps a paragraph across
    # several lines while Word keeps it as one: searching line by line finds a long phrase
    # in the .docx and misses the identical phrase in the .pdf.
    line_start: list[int] = []
    cursor = 0
    for ln in lines:
        line_start.append(cursor)
        cursor += len(ln) + 1

    def line_of(offset: int) -> int:
        return bisect.bisect_right(line_start, offset) - 1

    image_count = len(images_in_docx(data)) if fmt == "docx" else images_in_pdf(data)

    # 1. Every system in the catalogue has a heading of its own.
    systems = list(catalogue.systems())
    heading_at = {
        s.name: next((i for i, ln in enumerate(lines) if ln == s.name), -1) for s in systems
    }
    missing = [name for name, at in heading_at.items() if at < 0]
    report.add(
        "every inspection system appears",
        not missing,
        f"missing: {missing}" if missing else f"{len(systems)} systems",
    )

    # 2. Those headings appear in catalogue order — the report's promised order.
    present = [(s.name, heading_at[s.name]) for s in systems if heading_at[s.name] >= 0]
    ordered = [n for n, _ in sorted(present, key=lambda p: p[1])]
    report.add(
        "systems appear in catalogue order",
        ordered == [n for n, _ in present],
        f"found {ordered}" if ordered != [n for n, _ in present] else "",
    )

    # 3. Every finding sits between its own system's heading and the next one. This is the
    #    card's requirement, so it is checked by position, not by presence.
    misplaced: list[str] = []
    boundaries = sorted(at for _, at in present)
    for finding in inspection.findings:
        system_name = catalogue.system(finding.system_key).name
        needle = " ".join(finding.prose().split())[:60]
        offset = flat.find(needle)
        if offset < 0:
            misplaced.append(f"{needle[:32]!r} not in the file")
            continue
        at = line_of(offset)
        start = heading_at.get(system_name, -1)
        after = [b for b in boundaries if b > start]
        end = after[0] if after else len(lines)
        if not (start < at < end):
            misplaced.append(f"{needle[:32]!r} is not under {system_name}")
    report.add(
        "every finding is under its own system",
        not misplaced,
        "; ".join(misplaced[:3]) if misplaced else f"{len(inspection.findings)} findings",
    )

    # 4. Severity labels survived.
    labels = {catalogue.severity(f.severity_key).label for f in inspection.findings}
    absent = [x for x in labels if x not in flat]
    report.add(
        "severity labels are present",
        not absent,
        f"missing: {absent}" if absent else f"{len(labels)} distinct labels",
    )

    # 5. The photographs are in the file, not merely referenced.
    #
    #    Counted against what the inspector *recorded*, not against what happened to reach
    #    the service. Comparing only against uploaded photographs made the check vacuous in
    #    the exact case it exists for: an inspection holding eight photographs whose uploads
    #    never happened exported with none, and this said "0 embedded, 0 expected — PASS".
    #    A report that quietly loses its evidence is the failure, not the bookkeeping.
    recorded = sum(len(f.photos) for f in inspection.findings)
    uploaded = sum(1 for f in inspection.findings for p in f.photos if p.uploaded)
    detail = f"{image_count} embedded, {recorded} recorded"
    if uploaded < recorded:
        detail += f" ({recorded - uploaded} never reached the service)"
    report.add(
        "photographs are embedded in the file",
        True
        if not expect_photos
        else (image_count >= uploaded and not (recorded > 0 and image_count == 0)),
        detail,
    )

    # 6. The language rail holds in the finished bytes — not just at the gate. But *whose*
    #    words tripped it decides whether this is a failure or a note.
    #
    #    The rail governs generated text and never overwrites the inspector: they are the
    #    licensed professional, the report is theirs, and the gate tells them their wording
    #    is kept exactly as written. Running the rail over the finished file and failing the
    #    export when their own sentence says "is safe" contradicts that promise — and does
    #    something worse than annoy them. It buries the failure that actually matters. A
    #    system that generated a certifying sentence and an inspector who wrote one are not
    #    the same event, and if the export routinely fails for the second, nobody will look
    #    at the first.
    #
    #    So the two are separated by attribution: anything traceable to a finding's own
    #    observation or recommendation is reported and never fails the export; anything else
    #    got into the document some other way, which is the thing this build exists to
    #    prevent.
    verdict = rail.check(flat)
    inspector_words = " ".join(
        " ".join(f"{f.observation} {f.recommendation}".split()).lower() for f in inspection.findings
    )
    theirs = [b for b in verdict.breaches if b.matched.lower() in inspector_words]
    ours = [b for b in verdict.breaches if b.matched.lower() not in inspector_words]
    report.add(
        "no certification language the system produced",
        not ours,
        _phrases(ours),
    )
    if theirs:
        # Recorded, never failed. It is a real thing a reader should know about the document
        # and a real thing the inspector is entitled to have said.
        report.add(
            "the inspector's own wording carries claims (kept as written)",
            True,
            _phrases(theirs),
        )

    # 7. A capability URL never travels inside a document that gets emailed around.
    report.add(
        "no photo URLs leaked into the document text",
        "superdocs-document-images" not in flat,
        "a storage URL appears in the exported text" if "superdocs-document-images" in flat else "",
    )

    return report
