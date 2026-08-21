"""Model -> HTML, and model -> generator spec.

Used only by the offline FakeClient, to give it a real round-trip
(docx -> model -> html -> model -> docx) rather than a stub that hands back
what it was given. A fake that returns the input unchanged would make every
test pass and prove nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from xml.sax.saxutils import escape

from .model import Cell, Document, Table


def _cell_html(c: Cell) -> str:
    attrs = []
    if c.col_span > 1:
        attrs.append(f'colspan="{c.col_span}"')
    if c.row_span > 1:
        attrs.append(f'rowspan="{c.row_span}"')
    style = []
    if c.alignment:
        style.append(f"text-align:{c.alignment}")
    if c.shading:
        style.append(f"background-color:#{c.shading}")
    if c.valign:
        style.append(f"vertical-align:{c.valign}")
    if style:
        attrs.append('style="' + ";".join(style) + '"')
    if c.text_direction:
        attrs.append(f'data-dir="{c.text_direction}"')
    if c.width_dxa is not None:
        attrs.append(f'data-w="{c.width_dxa}"')
    for edge, spec in sorted(c.borders.items()):
        attrs.append(f'data-border-{edge}="{spec}"')
    open_tag = "<td" + (" " + " ".join(attrs) if attrs else "") + ">"

    body = "".join(f"<p>{escape(p)}</p>" for p in c.paragraphs if p != "")
    for nt in c.nested:
        body += _table_html(nt)
    return open_tag + body + "</td>"


def _table_html(t: Table) -> str:
    anchors = t.anchors()
    rows_html = []
    for r in range(t.n_rows):
        cells = [anchors[(rr, cc)] for (rr, cc) in sorted(anchors) if rr == r]
        cells.sort(key=lambda c: c.col)
        if not cells:
            continue
        rows_html.append("<tr>" + "".join(_cell_html(c) for c in cells) + "</tr>")
    attrs = ""
    if t.header_rows:
        attrs += f' data-header-rows="{",".join(str(r) for r in t.header_rows)}"'
    if t.layout:
        attrs += f' data-layout="{t.layout}"'
    cols = ""
    if t.col_widths:
        cols = "<colgroup>" + "".join(
            f'<col data-w="{w}"/>' for w in t.col_widths) + "</colgroup>"
    return f"<table{attrs}>" + cols + "".join(rows_html) + "</table>"


def to_html(doc: Document) -> str:
    parts = [f"<p>{escape(p)}</p>" for p in doc.body_paragraphs[:2]]
    parts += [_table_html(t) for t in doc.tables]
    parts += [f"<p>{escape(p)}</p>" for p in doc.body_paragraphs[2:]]
    return "".join(parts)


# --------------------------------------------------------------------------

@dataclass
class _SyntheticCase:
    """Duck-types the fields corpus.generate.write_docx reads off a Case."""

    title: str = ""
    intro: str = ""
    tables: list[dict] = field(default_factory=list)
    trailing_paragraphs: list[str] = field(default_factory=list)


def _table_to_spec(t: Table) -> dict:
    anchors = t.anchors()
    rows: list[list[dict]] = []
    for r in range(t.n_rows):
        line = [c for (rr, _), c in sorted(anchors.items()) if rr == r]
        line.sort(key=lambda c: c.col)
        spec_row = []
        for c in line:
            d: dict = {"paragraphs": list(c.paragraphs) or [""]}
            if c.col_span > 1:
                d["colspan"] = c.col_span
            if c.row_span > 1:
                d["rowspan"] = c.row_span
            if c.alignment:
                d["align"] = c.alignment
            if c.shading:
                d["fill"] = c.shading
            if c.valign:
                d["valign"] = c.valign
            if c.text_direction:
                d["dir"] = c.text_direction
            if c.borders:
                bd = {}
                for edge, spec in c.borders.items():
                    parts = spec.split("/")
                    if len(parts) == 3:
                        bd[edge] = (parts[1], parts[2])
                if bd:
                    d["borders"] = bd
            if c.nested:
                d["nested"] = _table_to_spec(c.nested[0])
            spec_row.append(d)
        if spec_row:
            rows.append(spec_row)
    spec = {"rows": rows, "header_rows": list(t.header_rows)}
    if t.col_widths:
        spec["col_widths"] = list(t.col_widths)
    if t.layout:
        spec["layout"] = t.layout
    return spec


def doc_to_case(doc: Document) -> _SyntheticCase:
    bp = doc.body_paragraphs
    return _SyntheticCase(
        title=bp[0] if bp else "",
        intro=bp[1] if len(bp) > 1 else "",
        tables=[_table_to_spec(t) for t in doc.tables],
        trailing_paragraphs=list(bp[2:]),
    )
