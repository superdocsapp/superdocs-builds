"""The shipped report formats, authored as Word documents.

These are the product's answer to the card's premise. The brief says inspection reports are
not written for a buyer who has never read one, so a builder that asks a firm to upload its
existing report and binds data into it would faithfully reproduce the problem it exists to
solve. The formats ship, and a firm chooses among them — or opens one in Word, changes it,
and drops it back in, because it is a Word document and not a markup dialect.

**How they are designed, and why that is in code.** A format is the firm's document: it goes
to a buyer, an agent and a lender, and it is the only thing any of them ever sees. So these
are set rather than typed — a masthead closed by a heavy rule, small-caps letterspaced
labels, section headings on their own rules, a severity legend with real colour swatches, a
footer that says which property and which page. Generating them from code rather than
committing opaque `.docx` blobs keeps that reviewable in a pull request, keeps the catalogue
as the single source of the systems and the scale, and keeps the three formats consistent
with each other.

**Colour is spent on severity and on nothing else.** The headings are a deep slate — a
neutral, not a hue — so the only real chroma in the document is the severity scale, which is
the one thing a buyer has to pick out at a glance. A brand accent competing with it would be
a hazard rather than a flourish.

Every format must satisfy :func:`inspection_report.templates.binding.read_format`: a heading
per catalogue system with a ``[findings]`` slot under it, and one worked example showing how
a finding is recorded. The test suite holds all three to exactly that. Tokens live in
paragraphs and never inside a table, because a table is a different kind of block on the way
through SuperDocs and the binder anchors on paragraphs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
from docx.shared import Inches, Pt, RGBColor

from inspection_report.domain import catalogue
from inspection_report.templates import wordcraft as wc

# The document's ink. A deep slate rather than black — black on white is harsher than print
# and reads cheaper — with two greys for supporting text and rules.
INK = RGBColor(0x11, 0x13, 0x18)
INK_SOFT = RGBColor(0x4A, 0x4F, 0x57)
INK_FAINT = RGBColor(0x7A, 0x7F, 0x87)
RULE_HAIR = "C9C6BC"

BODY = "Georgia"
LABEL = "Helvetica Neue"

PREAMBLE = (
    "This report records what was observed at the property on the date of the inspection. "
    "It is a visual examination of the systems listed below and is not a certification, "
    "warranty or guarantee of the condition of the property. Where an item is recommended "
    "for further evaluation, that means a qualified specialist should look at it before you "
    "rely on it."
)

LIMITS = (
    "Only areas that were visible and safely accessible on the day were examined. Anything "
    "concealed by finishes, stored belongings, insulation or weather was not inspected, and "
    "nothing in this report should be read as a statement about those areas. Conditions at a "
    "property change, and this report describes one day."
)

GROUPING_NOTE = (
    "Findings are grouped by the system they belong to, and within each system the items "
    "that warrant the soonest attention come first. Every entry records what was observed "
    "and what is recommended next."
)

EXAMPLE_HEADING = "How each finding is recorded"
EXAMPLE_NOTE = (
    "This section shows the shape every finding below takes. It is part of the format, not "
    "part of a finished report, and it is removed when a report is produced."
)


# ----------------------------------------------------------------- pieces


def _overline(doc: Any, text: str, *, space: float = 0) -> Any:
    """A small-caps letterspaced label. Does the work a coloured chip would do elsewhere."""
    paragraph = doc.add_paragraph()
    if space:
        wc.space_before(paragraph, space)
    paragraph.paragraph_format.space_after = Pt(2)
    run = paragraph.add_run(text)
    run.font.name = LABEL
    run.font.size = Pt(7.5)
    run.font.bold = True
    run.font.color.rgb = INK_FAINT
    wc.small_caps(run)
    wc.letterspace(run, 30)
    return paragraph


def _heading(doc: Any, text: str, *, level: int = 1) -> Any:
    """A section heading on its own rule. Word's built-in styles are what make a document
    look like a template; these are set from scratch so the format looks like a report."""
    paragraph = doc.add_heading("", level=level)
    paragraph.paragraph_format.space_before = Pt(20)
    paragraph.paragraph_format.space_after = Pt(7)
    run = paragraph.add_run(text)
    run.font.name = BODY
    run.font.size = Pt(14 if level == 1 else 11.5)
    run.font.bold = True
    run.font.color.rgb = INK
    run.font.all_caps = False
    wc.rule(paragraph, edge="bottom", size=6, colour=RULE_HAIR, space=6)
    wc.keep_with_next(paragraph)
    return paragraph


def _body(doc: Any, text: str, *, size: float = 10, colour: RGBColor = INK_SOFT) -> Any:
    paragraph = doc.add_paragraph()
    paragraph.paragraph_format.space_after = Pt(7)
    run = paragraph.add_run(text)
    run.font.name = BODY
    run.font.size = Pt(size)
    run.font.color.rgb = colour
    return paragraph


def _masthead(doc: Any, subtitle: str) -> None:
    """The title block: the firm, what this is, and the three facts that identify it."""
    name = doc.add_paragraph()
    name.alignment = WD_ALIGN_PARAGRAPH.CENTER
    name.paragraph_format.space_after = Pt(3)
    run = name.add_run("[firm name]")
    run.font.name = BODY
    run.font.size = Pt(23)
    run.font.bold = True
    run.font.color.rgb = INK
    wc.letterspace(run, 20)

    sub = doc.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sub.paragraph_format.space_after = Pt(10)
    srun = sub.add_run(subtitle)
    srun.font.name = LABEL
    srun.font.size = Pt(8)
    srun.font.color.rgb = INK_FAINT
    wc.small_caps(srun)
    wc.letterspace(srun, 60)
    # The heavy rule that closes a masthead. This one line is most of what separates a
    # designed document from a typed one.
    wc.rule(sub, edge="bottom", size=18, colour="111318", space=10)

    for label, token in (
        ("Property", "[property address]"),
        ("Inspected by", "[inspector]"),
        ("Date of inspection", "[date of inspection]"),
    ):
        row = doc.add_paragraph()
        row.paragraph_format.space_after = Pt(1)
        # An explicit left stop. Without the alignment argument Word falls back to its own
        # half-inch defaults and the values step raggedly right as the labels lengthen.
        row.paragraph_format.tab_stops.add_tab_stop(Inches(1.6), WD_TAB_ALIGNMENT.LEFT)
        key = row.add_run(label)
        key.font.name = LABEL
        key.font.size = Pt(7.5)
        key.font.color.rgb = INK_FAINT
        wc.small_caps(key)
        wc.letterspace(key, 25)
        row.add_run("\t")
        value = row.add_run(token)
        value.font.name = BODY
        value.font.size = Pt(10.5)
        value.font.color.rgb = INK
    doc.paragraphs[-1].paragraph_format.space_after = Pt(4)


def _legend(doc: Any) -> None:
    """The severity scale, each level marked with its own colour.

    The swatch is a glyph rather than a shaded table cell. A cell's fill survives the trip to
    HTML but its *width* does not — every exporter reweights the columns — so a 4mm marker
    arrived as a slab across a third of the page. Run colour survives everywhere, which makes
    the glyph the version that actually renders. This is the only colour in the document, and
    it is the one thing a buyer has to pick out at a glance.
    """
    _heading(doc, "Severity labels used in this report")
    for severity in catalogue.severities():
        row = doc.add_paragraph()
        row.paragraph_format.space_after = Pt(5)
        row.paragraph_format.left_indent = Inches(0.02)

        swatch = row.add_run("\u25a0")  # ■
        swatch.font.name = LABEL
        swatch.font.size = Pt(11)
        swatch.font.color.rgb = RGBColor.from_string(severity.colour.lstrip("#").upper())

        gap = row.add_run("   ")
        gap.font.size = Pt(10)

        # Deliberately not small caps. The verifier reads the finished file back and holds
        # it to this exact string; small caps renders it upper-case and a text extractor
        # then cannot find it. Presentation does not get to break a guarantee — the weight
        # and the tracking carry the same emphasis without touching the letters.
        label = row.add_run(severity.label)
        label.font.name = LABEL
        label.font.size = Pt(8.5)
        label.font.bold = True
        label.font.color.rgb = INK
        wc.letterspace(label, 12)

        dash = row.add_run("   ")
        dash.font.size = Pt(10)

        text = row.add_run(severity.description.strip())
        text.font.name = BODY
        text.font.size = Pt(9.5)
        text.font.color.rgb = INK_SOFT


def _worked_example(doc: Any, *, with_photos: bool, with_recommendation: bool = True) -> None:
    """One finding, shown in the shape every finding takes.

    The binder reads these paragraphs *as* the per-finding template, so they must stay
    contiguous — a spacer between them would break the run it looks for.
    """
    _heading(doc, EXAMPLE_HEADING)
    _body(doc, EXAMPLE_NOTE, size=9.5, colour=INK_FAINT)

    title = doc.add_paragraph()
    title.paragraph_format.space_before = Pt(6)
    title.paragraph_format.space_after = Pt(3)
    wc.rule(title, edge="top", size=4, colour=RULE_HAIR, space=8)
    # Same reason as the legend: this token becomes the severity label, and the label has to
    # survive being read back out of the exported file exactly as written.
    severity = title.add_run("[severity label]")
    severity.font.name = LABEL
    severity.font.size = Pt(8.5)
    severity.font.bold = True
    severity.font.color.rgb = INK_SOFT
    wc.letterspace(severity, 12)
    sep = title.add_run("   ")
    sep.font.size = Pt(8)
    where = title.add_run("[location]")
    where.font.name = BODY
    where.font.size = Pt(11)
    where.font.bold = True
    where.font.color.rgb = INK

    observation = doc.add_paragraph()
    observation.paragraph_format.space_after = Pt(4)
    obs = observation.add_run("[observation]")
    obs.font.name = BODY
    obs.font.size = Pt(10)
    obs.font.color.rgb = INK

    if with_recommendation:
        rec = doc.add_paragraph()
        rec.paragraph_format.space_after = Pt(6)
        label = rec.add_run("Recommended next step   ")
        label.font.name = LABEL
        label.font.size = Pt(7.5)
        label.font.bold = True
        label.font.color.rgb = INK_FAINT
        wc.small_caps(label)
        wc.letterspace(label, 25)
        value = rec.add_run("[recommendation]")
        value.font.name = BODY
        value.font.size = Pt(10)
        value.font.color.rgb = INK_SOFT

    if with_photos:
        photo = doc.add_paragraph()
        photo.paragraph_format.space_after = Pt(2)
        photo.add_run("[photograph]")
        caption = doc.add_paragraph()
        caption.paragraph_format.space_after = Pt(10)
        crun = caption.add_run("[caption]")
        crun.font.name = BODY
        crun.font.size = Pt(8.5)
        crun.font.italic = True
        crun.font.color.rgb = INK_FAINT


def _system_sections(doc: Any, *, with_blurb: bool = True, with_summary: bool = True) -> None:
    for system in catalogue.systems():
        _heading(doc, system.name)
        if with_blurb:
            blurb = doc.add_paragraph()
            blurb.paragraph_format.space_after = Pt(6)
            brun = blurb.add_run(system.blurb.strip())
            brun.font.name = BODY
            brun.font.size = Pt(9.5)
            brun.font.italic = True
            brun.font.color.rgb = INK_FAINT
        if with_summary:
            _overline(doc, "[system summary]")
        _body(doc, "[findings]", size=10, colour=INK)


def _base(subtitle: str, *, footer_note: str) -> Any:
    doc = Document()

    style = doc.styles["Normal"]
    style.font.name = BODY
    style.font.size = Pt(10)
    style.font.color.rgb = INK
    style.paragraph_format.space_after = Pt(6)
    style.paragraph_format.line_spacing = 1.18

    section = doc.sections[0]
    section.start_type = WD_SECTION.NEW_PAGE
    section.top_margin = Inches(0.9)
    section.bottom_margin = Inches(0.85)
    section.left_margin = Inches(1.0)
    section.right_margin = Inches(1.0)
    wc.page_footer(section, left=footer_note, ink=INK_FAINT)

    _masthead(doc, subtitle)
    return doc


# ---------------------------------------------------------------- formats


def buyer_summary() -> Any:
    """The default: written for someone who has never read an inspection report."""
    doc = _base("Residential Property Inspection Report", footer_note="[property address]")
    _heading(doc, "How to read this report")
    _body(doc, PREAMBLE)
    _body(doc, GROUPING_NOTE + " Photographs are included so you can see what is being described.")
    _legend(doc)
    _worked_example(doc, with_photos=True)
    _heading(doc, "What was inspected")
    _body(doc, "[systems inspected]")
    _system_sections(doc)
    _heading(doc, "Scope and limits of this inspection")
    _body(doc, LIMITS, size=9.5, colour=INK_FAINT)
    return doc


def full_technical() -> Any:
    """Everything, for the file: the same findings with the scope carried up front."""
    doc = _base("Full Technical Inspection Report", footer_note="[property address]")
    _heading(doc, "Scope of this inspection")
    _body(doc, PREAMBLE)
    _body(doc, LIMITS, size=9.5, colour=INK_FAINT)
    _heading(doc, "How to read this report")
    _body(doc, GROUPING_NOTE)
    _legend(doc)
    _worked_example(doc, with_photos=True)
    _heading(doc, "Systems examined")
    _body(doc, "[systems inspected]")
    _system_sections(doc)
    _heading(doc, "Limitations")
    _body(doc, LIMITS, size=9.5, colour=INK_FAINT)
    return doc


def repair_priority() -> Any:
    """A working list for getting quotes: no photographs, no blurbs, the actions only."""
    doc = _base("Repair Priority List", footer_note="[property address]")
    _heading(doc, "What this list is")
    _body(doc, PREAMBLE)
    _body(
        doc,
        "This list carries the same findings as the full report, ordered so the items that "
        "warrant the soonest attention appear first under each system. It is intended for "
        "taking to contractors for quotes. It carries no photographs; the full report does.",
        size=9.5,
        colour=INK_FAINT,
    )
    _legend(doc)
    _worked_example(doc, with_photos=False)
    _heading(doc, "Systems covered")
    _body(doc, "[systems inspected]")
    _system_sections(doc, with_blurb=False, with_summary=False)
    _heading(doc, "Scope and limits")
    _body(doc, LIMITS, size=9.5, colour=INK_FAINT)
    return doc


FORMATS = {
    "buyer_summary": buyer_summary,
    "full_technical": full_technical,
    "repair_priority": repair_priority,
}


def write_all(directory: Path) -> list[Path]:
    """Author every shipped format into ``directory``. Returns the paths written."""
    directory.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for key, builder in sorted(FORMATS.items()):
        path = directory / f"{key}.docx"
        builder().save(str(path))
        written.append(path)
    return written
