"""Post-process a SuperDocs .docx export into a submission-shaped document.

Two transformations, both strictly additive to what the model drafted:

1. ``convert_citations_to_footnotes`` — inline bracketed citations like
   ``[Study Report 1, Section 1.1]`` become real Word footnotes. The bracketed
   span is removed from the paragraph text and replaced by a clickable footnote
   reference mark; the citation text moves to the footnote area at the bottom
   of the page. Only citations fully contained inside a single run are
   converted; anything else is left byte-for-byte untouched (graceful
   degradation, never a lossy rewrite).

2. ``make_live_toc`` — the placeholder bullet list under the "Table of
   Contents" heading is replaced by a real Word ``TOC`` field (instrText
   ``TOC \\o "1-3"``). Marked dirty, so Word populates it (with page numbers)
   the moment the file is opened.
"""

import re
from copy import deepcopy
from xml.sax.saxutils import escape

from docx import Document
from docx.opc.constants import CONTENT_TYPE as CT
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.opc.packuri import PackURI
from docx.opc.part import Part
from docx.oxml import parse_xml
from docx.oxml.ns import nsmap, qn

W_NS = nsmap["w"]

CITATION_RE = re.compile(r"\[([^\]]+)\]")
_CITATION_HINTS = ("report", "section", "module", "study")


def _is_citation_text(text: str) -> bool:
    """True only when the bracketed content points at a source. Requires both a
    source hint word and a number, so a placeholder like '[Table of contents
    will be generated.]' is never mistaken for a citation."""
    lowered = text.lower()
    return any(hint in lowered for hint in _CITATION_HINTS) and any(
        c.isdigit() for c in text
    )

_TOC_FIELD_XML = (
    f'<w:p xmlns:w="{W_NS}">'
    '<w:r><w:fldChar w:fldCharType="begin" w:dirty="true"/></w:r>'
    '<w:r><w:instrText xml:space="preserve"> TOC \\o "1-3" \\h \\z \\u </w:instrText></w:r>'
    '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
    "<w:r><w:t>Open in Word and update fields to populate the table of contents.</w:t></w:r>"
    '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
    "</w:p>"
)

FOOTNOTE_REF_RUN_XML = (
    f'<w:r xmlns:w="{W_NS}">'
    "<w:rPr>"
    '<w:rStyle w:val="FootnoteReference"/>'
    '<w:vertAlign w:val="superscript"/>'
    "</w:rPr>"
    '<w:footnoteReference w:id="{fid}"/>'
    "</w:r>"
)

_FOOTNOTE_BODY_XML = (
    f'<w:footnote xmlns:w="{W_NS}" w:id="{{fid}}">'
    "<w:p>"
    "<w:pPr>"
    '<w:pStyle w:val="FootnoteText"/>'
    '<w:spacing w:after="0" w:line="240" w:lineRule="auto"/>'
    "</w:pPr>"
    "<w:r>"
    "<w:rPr>"
    '<w:rStyle w:val="FootnoteReference"/>'
    '<w:vertAlign w:val="superscript"/>'
    "</w:rPr>"
    "<w:footnoteRef/>"
    "</w:r>"
    '<w:r><w:t xml:space="preserve"> {text}</w:t></w:r>'
    "</w:p>"
    "</w:footnote>"
)


def _footnotes_part_xml(citation_texts: list[str]) -> bytes:
    """Build the complete word/footnotes.xml document, id -1/0 reserved for
    separators and ids 1..n for the real footnotes."""
    parts = [
        f'<w:footnote xmlns:w="{W_NS}" w:type="separator" w:id="-1">'
        "<w:p><w:pPr><w:spacing w:after=\"0\" w:line=\"240\" w:lineRule=\"auto\"/></w:pPr>"
        "<w:r><w:separator/></w:r></w:p>"
        "</w:footnote>",
        f'<w:footnote xmlns:w="{W_NS}" w:type="continuationSeparator" w:id="0">'
        "<w:p><w:pPr><w:spacing w:after=\"0\" w:line=\"240\" w:lineRule=\"auto\"/></w:pPr>"
        "<w:r><w:continuationSeparator/></w:r></w:p>"
        "</w:footnote>",
    ]
    for fid, text in enumerate(citation_texts, start=1):
        parts.append(_FOOTNOTE_BODY_XML.format(fid=fid, text=escape(text)))
    xml = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:footnotes xmlns:w="{W_NS}">{"".join(parts)}</w:footnotes>'
    )
    return xml.encode("utf-8")


def _run_direct_children(run) -> set[str]:
    return {c.tag.split("}")[1] for c in run}


def _iter_convertible_runs(paragraph):
    """Yield runs that hold plain text only (w:t with optional w:rPr), i.e. runs
    we can safely split without destroying inline structure."""
    for run in paragraph._p.findall(qn("w:r")):
        if not _run_direct_children(run).issubset({"rPr", "t"}):
            continue
        yield run


def _clone_run_with_text(template, text: str):
    new_run = deepcopy(template)
    for child in list(new_run):
        tag = child.tag.split("}")[1]
        if tag in ("t", "footnoteReference"):
            new_run.remove(child)
    text_el = new_run.makeelement(qn("w:t"), {})
    text_el.set(qn("xml:space"), "preserve")
    text_el.text = text
    new_run.append(text_el)
    return new_run


def _split_run(run, matches, footnote_ids: list[str], next_fid) -> int:
    """Replace citation spans in `run` with footnote reference marks. Returns
    the number of citations converted (0 if none qualified)."""
    text = "".join(t.text or "" for t in run.findall(qn("w:t")))
    new_runs = []
    pos = 0
    fid = next_fid
    converted = 0
    for m in matches:
        if not _is_citation_text(m.group(1)):
            continue
        if m.start() > pos:
            new_runs.append(_clone_run_with_text(run, text[pos : m.start()]))
        footnote_ids.append(m.group(1))
        new_runs.append(parse_xml(FOOTNOTE_REF_RUN_XML.format(fid=fid)))
        fid += 1
        converted += 1
        pos = m.end()
    if pos < len(text):
        new_runs.append(_clone_run_with_text(run, text[pos:]))
    if not new_runs:
        return 0

    parent = run.getparent()
    current = new_runs[0]
    parent.replace(run, current)
    for extra in new_runs[1:]:
        current.addnext(extra)
        current = extra
    return converted


def convert_citations_to_footnotes(doc: Document) -> int:
    """Convert inline ``[...]`` citations to real Word footnotes. Returns the
    number of footnotes created (0 means nothing was converted)."""
    footnote_texts: list[str] = []
    next_fid = 1

    for paragraph in doc.paragraphs:
        for run in _iter_convertible_runs(paragraph):
            text = "".join(t.text or "" for t in run.findall(qn("w:t")))
            matches = list(CITATION_RE.finditer(text))
            if not matches:
                continue
            next_fid += _split_run(run, matches, footnote_texts, next_fid)

    if not footnote_texts:
        return 0

    document_part = doc.part
    footnotes_part = Part(
        PackURI("/word/footnotes.xml"),
        CT.WML_FOOTNOTES,
        _footnotes_part_xml(footnote_texts),
        document_part.package,
    )
    document_part.relate_to(footnotes_part, RT.FOOTNOTES)
    return len(footnote_texts)


def _paragraph_style_name(p) -> str:
    p_pr = p.find(qn("w:pPr"))
    if p_pr is None:
        return ""
    p_style = p_pr.find(qn("w:pStyle"))
    if p_style is None:
        return ""
    return p_style.get(qn("w:val")) or ""


def make_live_toc(doc: Document) -> bool:
    """Replace the bullet list under the 'Table of Contents' heading with a real
    Word TOC field. Returns True if the field was inserted."""
    body = doc.element.body
    toc_heading = None
    for p in body.findall(qn("w:p")):
        text = "".join(t.text or "" for t in p.iter(qn("w:t"))).strip()
        if text == "Table of Contents":
            toc_heading = p
            break
    if toc_heading is None:
        return False

    to_delete = []
    el = toc_heading.getnext()
    while el is not None:
        if el.tag == qn("w:p"):
            style = _paragraph_style_name(el)
            if style.startswith("Heading"):
                break
            to_delete.append(el)
        elif el.tag == qn("w:sectPr"):
            break
        el = el.getnext()

    for old in to_delete:
        body.remove(old)

    toc_heading.addnext(parse_xml(_TOC_FIELD_XML))
    return True


def postprocess_export(src_path: str, dst_path: str) -> dict:
    """Open a SuperDocs export, convert citations to footnotes, inject the live
    TOC field, and save the submission-shaped document. Returns a small report
    so callers can surface exactly what changed."""
    doc = Document(src_path)
    footnote_count = convert_citations_to_footnotes(doc)
    toc_inserted = make_live_toc(doc)
    doc.save(dst_path)
    return {"footnotes_created": footnote_count, "live_toc_inserted": toc_inserted}
