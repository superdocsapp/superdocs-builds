from __future__ import annotations

import io
import re
from datetime import UTC, datetime
from typing import Any

import docx
from docx.oxml.ns import qn
from docx.oxml.shared import OxmlElement

from ..core.store import ProposalRow

SIDE_AUTHORS = {"vendor": "Vendor", "customer": "Customer"}


def _clean_html(html_text: str | None) -> str:
    import html as html_mod

    if not html_text:
        return ""
    return html_mod.unescape(re.sub(r"<[^>]+>", "", html_text)).strip()


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()


def _run(text: str, tag: str = "w:r") -> OxmlElement:
    r = OxmlElement("w:r")
    text_tag = "w:delText" if tag == "w:delText" else "w:t"
    t = OxmlElement(text_tag)
    t.set(qn("xml:space"), "preserve")
    t.text = text
    r.append(t)
    return r


def _del_run(text: str) -> OxmlElement:
    r = OxmlElement("w:r")
    d = OxmlElement("w:delText")
    d.set(qn("xml:space"), "preserve")
    d.text = text
    r.append(d)
    return r


def _wrap(kind: str, run: OxmlElement, author: str, date: str, rev_id: int) -> OxmlElement:
    wrapper = OxmlElement(kind)
    wrapper.set(qn("w:id"), str(rev_id))
    wrapper.set(qn("w:author"), author)
    wrapper.set(qn("w:date"), date)
    wrapper.append(run)
    return wrapper


class _RevisionIdCounter:
    def __init__(self) -> None:
        self._value = 0

    def next(self) -> int:
        self._value += 1
        return self._value


def _find_paragraph(document: docx.Document, needle: str):
    target = _normalize(needle)
    if not target:
        return None
    for paragraph in document.paragraphs:
        if _normalize(paragraph.text) == target:
            return paragraph
    for paragraph in document.paragraphs:
        if target in _normalize(paragraph.text):
            return paragraph
    return None


def _apply_edit(
    document: docx.Document, proposal: ProposalRow, author: str, date: str, ids: _RevisionIdCounter
) -> Any | None:
    """Apply an edit and return the paragraph it landed on, or None if unmatched.

    The paragraph is returned rather than a bool so the caller can remember which
    paragraph a chunk id refers to; a later `create` anchored to that chunk can then be
    positioned exactly instead of appended.
    """
    old_text = _clean_html(proposal.old_html)
    paragraph = _find_paragraph(document, old_text)
    if paragraph is None:
        return None
    p = paragraph._p
    for run_element in p.findall(qn("w:r")):
        p.remove(run_element)
    new_text = _clean_html(proposal.new_html)
    p.append(_wrap("w:del", _del_run(old_text), author, date, ids.next()))
    if new_text:
        p.append(_wrap("w:ins", _run(new_text), author, date, ids.next()))
    return paragraph


def _apply_delete(
    document: docx.Document, proposal: ProposalRow, author: str, date: str, ids: _RevisionIdCounter
) -> Any | None:
    """Apply a deletion and return the paragraph it landed on, or None if unmatched."""
    old_text = _clean_html(proposal.old_html)
    paragraph = _find_paragraph(document, old_text)
    if paragraph is None:
        return None
    p = paragraph._p
    for run_element in p.findall(qn("w:r")):
        p.remove(run_element)
    p.append(_wrap("w:del", _del_run(old_text), author, date, ids.next()))
    return paragraph


def _chunk_ordinal(chunk_id: str | None) -> int | None:
    """Turn a SuperDocs chunk id such as 'c0007' into its 1-based position.

    Chunk ids are handed out in document order as the source is parsed, so the trailing
    number is the block's position. Anything that does not follow that shape returns
    None and the caller falls back rather than guessing.
    """
    if not chunk_id:
        return None
    digits = re.search(r"(\d+)\s*$", chunk_id)
    if not digits:
        return None
    ordinal = int(digits.group(1))
    return ordinal if ordinal > 0 else None


def _resolve_anchor(
    document: docx.Document, proposal: ProposalRow, located: dict[str, Any]
) -> Any | None:
    """Find the paragraph a created block should follow, or None to append.

    Two sources, best first. If an earlier edit or delete was matched by its text and
    carried the same chunk id, we know exactly which paragraph that chunk is, so we use
    it. Otherwise we fall back to the chunk's ordinal position. Out-of-range ordinals
    return None so the caller appends and reports the change as unmatched instead of
    dropping it somewhere arbitrary.
    """
    anchor_id = proposal.insert_after_chunk_id
    if not anchor_id:
        return None
    known = located.get(anchor_id)
    if known is not None:
        return known
    ordinal = _chunk_ordinal(anchor_id)
    if ordinal is None:
        return None
    paragraphs = document.paragraphs
    index = ordinal - 1
    if 0 <= index < len(paragraphs):
        return paragraphs[index]
    return None


def _apply_create(
    document: docx.Document,
    proposal: ProposalRow,
    author: str,
    date: str,
    ids: _RevisionIdCounter,
    anchor: Any | None = None,
) -> bool:
    """Insert the new text as a tracked insertion.

    Returns True when the block landed in a known position, False when it was appended
    at the end because no anchor could be resolved -- the caller reports that case
    honestly rather than letting a reader assume the position is meaningful.
    """
    new_text = _clean_html(proposal.new_html)
    paragraph = document.add_paragraph()
    p = paragraph._p
    p.append(_wrap("w:ins", _run(new_text), author, date, ids.next()))
    if anchor is None:
        return False
    p.getparent().remove(p)
    anchor._p.addnext(p)
    return True


def _append_heading(document: docx.Document, text: str, level: int = 1) -> None:
    document.add_heading(text, level=level)


def _append_table(document: docx.Document, rows: list[list[str]]) -> None:
    if not rows:
        return
    table = document.add_table(rows=1, cols=len(rows[0]))
    style_names = {s.name for s in document.styles}
    table.style = "Light Grid Accent 1" if "Light Grid Accent 1" in style_names else None
    header_cells = table.rows[0].cells
    headers = ["Change", "Proposed by", "Vendor", "Customer", "Feedback"]
    for i, h in enumerate(headers):
        header_cells[i].text = h
    for row in rows:
        cells = table.add_row().cells
        for i, value in enumerate(row):
            cells[i].text = value


def _proposal_summary(proposal: ProposalRow) -> str:
    old = _clean_html(proposal.old_html)
    new = _clean_html(proposal.new_html)
    if proposal.operation == "delete":
        return f"Delete: {old[:120]}"
    if proposal.operation == "create":
        return f"Add: {new[:120]}"
    return f"Edit: {old[:60]} -> {new[:60]}"


def build_redline_docx(
    original_filename: str, original_bytes: bytes, proposals: list[ProposalRow]
) -> bytes:
    """Build a lawyer-facing docx with OOXML track changes, generated locally from the
    original source document plus the recorded negotiation trail. Committed changes are
    rendered inline as w:ins/w:del attributed to the proposing side; rejected proposals are
    listed honestly in an appendix rather than silently dropped; changes whose original text
    could not be confidently located are called out explicitly rather than guessed at.
    """
    if original_filename.lower().endswith(".docx"):
        document = docx.Document(io.BytesIO(original_bytes))
    else:
        # Non-docx originals (md/txt/html) have no OOXML structure to overlay changes onto.
        # We still produce a usable docx, but it carries the negotiation trail as an
        # appendix rather than inline w:ins/w:del marks on the original prose.
        document = docx.Document()
        document.add_heading("Source document (converted, no inline redlines)", level=1)
        for line in original_bytes.decode("utf-8", errors="replace").splitlines():
            if line.strip():
                document.add_paragraph(line.strip())

    date = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    ids = _RevisionIdCounter()

    inline_capable = original_filename.lower().endswith(".docx")
    committed = [p for p in proposals if p.state == "committed"]
    rejected = [p for p in proposals if p.state == "rejected"]
    unmatched: list[ProposalRow] = []

    if inline_capable:
        # Two passes on purpose. Edits and deletes are located by their original text,
        # which teaches us which paragraph each chunk id refers to. Creates run second so
        # they can anchor to a chunk another change already pinned down, instead of
        # falling back to an ordinal guess or being appended at the end.
        located: dict[str, Any] = {}
        creates: list[ProposalRow] = []
        for proposal in committed:
            author = SIDE_AUTHORS.get(proposal.proposed_by_side, proposal.proposed_by_side)
            if proposal.operation == "edit":
                paragraph = _apply_edit(document, proposal, author, date, ids)
            elif proposal.operation == "delete":
                paragraph = _apply_delete(document, proposal, author, date, ids)
            else:
                creates.append(proposal)
                continue
            if paragraph is None:
                unmatched.append(proposal)
            elif proposal.chunk_id:
                located[proposal.chunk_id] = paragraph

        for proposal in creates:
            author = SIDE_AUTHORS.get(proposal.proposed_by_side, proposal.proposed_by_side)
            anchor = _resolve_anchor(document, proposal, located)
            placed = _apply_create(document, proposal, author, date, ids, anchor=anchor)
            if not placed:
                unmatched.append(proposal)
    else:
        unmatched.extend(committed)

    if unmatched:
        _append_heading(document, "Unmatched Changes", level=1)
        document.add_paragraph(
            "The following approved changes could not be confidently placed in the "
            "original document. Edits and deletions below could not be matched to their "
            "original text; additions below carried no usable position anchor and were "
            "appended at the end of the document rather than guessed at:"
        )
        for proposal in unmatched:
            document.add_paragraph(_proposal_summary(proposal), style=None)

    if rejected:
        _append_heading(document, "Appendix: Rejected Proposals", level=1)
        rows = [
            [
                _proposal_summary(p),
                SIDE_AUTHORS.get(p.proposed_by_side, p.proposed_by_side),
                p.vendor_decision or "-",
                p.customer_decision or "-",
                (p.vendor_feedback or p.customer_feedback or "-"),
            ]
            for p in rejected
        ]
        try:
            _append_table(document, rows)
        except Exception:
            for row in rows:
                document.add_paragraph(" | ".join(row))

    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


__all__ = ["build_redline_docx"]
