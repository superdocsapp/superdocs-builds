"""Extractors: DOCX -> Document, HTML -> Document.

Both target the same canonical model so any two stages of the pipeline are
directly comparable.

DOCX is parsed from raw WordprocessingML rather than through python-docx's
table API, because that API repeats merged cells instead of reporting spans,
which is precisely the thing under test here.
"""

from __future__ import annotations

import zipfile

from lxml import etree

from .model import Cell, Document, Table

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W}


def _q(tag: str) -> str:
    return f"{{{W}}}{tag}"


def _val(el, default=None):
    if el is None:
        return default
    return el.get(_q("val"), default)


# --------------------------------------------------------------------------
# DOCX
# --------------------------------------------------------------------------

def _para_text(p) -> str:
    """Text of one w:p, preserving tabs and explicit breaks."""
    out: list[str] = []
    for node in p.iter():
        tag = etree.QName(node).localname
        if tag == "t":
            out.append(node.text or "")
        elif tag == "tab":
            out.append("\t")
        elif tag == "br":
            out.append("\n")
    return "".join(out)


def _cell_paragraphs(tc) -> list[str]:
    """Paragraphs directly in this cell -- not those inside a nested table."""
    return [_para_text(p) for p in tc.findall(f"{_q('p')}")]


def _border_spec(e) -> str:
    return "{}/{}/{}".format(
        e.get(_q("val"), ""), e.get(_q("sz"), ""), (e.get(_q("color")) or "").upper()
    )


def _table_borders(tbl) -> dict[str, str]:
    """The table's own border declaration, by edge name."""
    tbl_pr = tbl.find(_q("tblPr"))
    if tbl_pr is None:
        return {}
    bdr = tbl_pr.find(_q("tblBorders"))
    if bdr is None:
        return {}
    return {etree.QName(e).localname: _border_spec(e) for e in bdr}


def _borders(pr) -> dict[str, str]:
    """Borders declared on the cell itself. May be empty."""
    if pr is None:
        return {}
    bdr = pr.find(_q("tcBorders"))
    if bdr is None:
        return {}
    out = {}
    for edge in ("top", "left", "bottom", "right"):
        e = bdr.find(_q(edge))
        if e is not None:
            out[edge] = _border_spec(e)
    return out


def _resolve_effective_borders(table: "Table", tbl_borders: dict[str, str]) -> None:
    """Fold table-level borders into every cell, in place.

    A round-trip is free to move a border from the table element onto each
    cell: the file changes, the rendered document does not. Comparing declared
    borders would call that re-expression a loss and bury the real findings
    under it. Comparing what each edge actually resolves to -- cell override
    first, then the table's outer edge or inner rule by position -- compares
    the document instead of the markup.
    """
    if not tbl_borders and not any(c.borders for c in table.cells):
        return
    for c in table.cells:
        eff = {}
        at_top = c.row == 0
        at_left = c.col == 0
        at_bottom = c.row + c.row_span >= table.n_rows
        at_right = c.col + c.col_span >= table.n_cols
        for edge, outer, inner in (
            ("top", at_top, "insideH"),
            ("bottom", at_bottom, "insideH"),
            ("left", at_left, "insideV"),
            ("right", at_right, "insideV"),
        ):
            spec = tbl_borders.get(edge) if outer else tbl_borders.get(inner)
            if spec:
                eff[edge] = spec
        eff.update(c.borders_declared)   # an explicit cell border always wins
        c.borders = {k: v for k, v in eff.items() if v}


def _parse_tbl(tbl) -> Table:
    table = Table()
    tbl_borders = _table_borders(tbl)

    grid = tbl.find(_q("tblGrid"))
    if grid is not None:
        for gc in grid.findall(_q("gridCol")):
            try:
                table.col_widths.append(int(gc.get(_q("w"), "0")))
            except ValueError:
                table.col_widths.append(0)

    tbl_pr = tbl.find(_q("tblPr"))
    if tbl_pr is not None:
        layout = tbl_pr.find(_q("tblLayout"))
        if layout is not None:
            table.layout = layout.get(_q("type"))

    occupied: dict[tuple[int, int], Cell] = {}
    rows = tbl.findall(_q("tr"))

    for r, tr in enumerate(rows):
        tr_pr = tr.find(_q("trPr"))
        if tr_pr is not None and tr_pr.find(_q("tblHeader")) is not None:
            table.header_rows.append(r)

        c = 0
        for tc in tr.findall(_q("tc")):
            while (r, c) in occupied:
                c += 1

            pr = tc.find(_q("tcPr"))
            span = 1
            vmerge = None
            if pr is not None:
                gs = pr.find(_q("gridSpan"))
                if gs is not None:
                    span = int(gs.get(_q("val"), "1"))
                vm = pr.find(_q("vMerge"))
                if vm is not None:
                    vmerge = vm.get(_q("val"), "continue")

            if vmerge == "continue":
                anchor = occupied.get((r - 1, c))
                if anchor is not None:
                    anchor.row_span = max(anchor.row_span, r - anchor.row + 1)
                    for k in range(span):
                        occupied[(r, c + k)] = anchor
                    c += span
                    continue
                # No anchor above: a broken vMerge. Treat as its own cell and
                # let the comparator report the topology difference honestly.
                vmerge = None

            shading = None
            valign = None
            width = None
            tdir = None
            if pr is not None:
                shd = pr.find(_q("shd"))
                if shd is not None:
                    fill = shd.get(_q("fill"))
                    if fill and fill.lower() not in ("auto",):
                        shading = fill.upper()
                va = pr.find(_q("vAlign"))
                valign = _val(va)
                tcw = pr.find(_q("tcW"))
                if tcw is not None:
                    try:
                        width = int(tcw.get(_q("w"), "0"))
                    except ValueError:
                        width = None
                td = pr.find(_q("textDirection"))
                tdir = _val(td)

            paras = tc.findall(_q("p"))
            alignment = None
            for p in paras:
                ppr = p.find(_q("pPr"))
                if ppr is not None:
                    j = ppr.find(_q("jc"))
                    if j is not None:
                        alignment = _val(j)
                        break

            cell = Cell(
                row=r,
                col=c,
                row_span=1,
                col_span=span,
                paragraphs=_cell_paragraphs(tc),
                alignment=alignment,
                shading=shading,
                valign=valign,
                width_dxa=width,
                text_direction=tdir,
                borders=_borders(pr),
                borders_declared=_borders(pr),
                nested=[_parse_tbl(t) for t in tc.findall(_q("tbl"))],
            )
            table.cells.append(cell)
            for k in range(span):
                occupied[(r, c + k)] = cell
            c += span

    table.n_rows = len(rows)
    table.n_cols = max((c.col + c.col_span for c in table.cells), default=0)
    if table.col_widths:
        table.n_cols = max(table.n_cols, len(table.col_widths))
    _resolve_effective_borders(table, tbl_borders)
    return table


def from_docx(path: str) -> Document:
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml")
    root = etree.fromstring(xml)
    body = root.find(_q("body"))
    doc = Document()
    if body is None:
        return doc
    for child in body:
        tag = etree.QName(child).localname
        if tag == "tbl":
            doc.tables.append(_parse_tbl(child))
        elif tag == "p":
            txt = _para_text(child)
            if txt.strip():
                doc.body_paragraphs.append(txt)
    return doc


# --------------------------------------------------------------------------
# HTML  (the SuperDocs intermediate representation)
# --------------------------------------------------------------------------

def _style_map(el) -> dict[str, str]:
    raw = el.get("style") or ""
    out = {}
    for part in raw.split(";"):
        if ":" in part:
            k, v = part.split(":", 1)
            out[k.strip().lower()] = v.strip()
    return out


def _html_cell_paragraphs(td) -> list[str]:
    from bs4 import NavigableString

    blocks = td.find_all(["p", "div"], recursive=False)
    if blocks:
        return [b.get_text().strip() for b in blocks]
    # Bare text in the cell, ignoring any nested table's text.
    parts = []
    for node in td.children:
        if isinstance(node, NavigableString):
            parts.append(str(node))
        elif getattr(node, "name", None) != "table":
            parts.append(node.get_text())
    text = "".join(parts).strip()
    return [text] if text else []


def _parse_html_table(tbl) -> Table:
    table = Table()
    occupied: dict[tuple[int, int], Cell] = {}

    rows = [tr for tr in tbl.find_all("tr") if tr.find_parent("table") is tbl]
    for r, tr in enumerate(rows):
        if tr.find_parent(["thead"]) is not None:
            table.header_rows.append(r)
        c = 0
        tds = [td for td in tr.find_all(["td", "th"]) if td.find_parent("tr") is tr]
        for td in tds:
            while (r, c) in occupied:
                c += 1
            try:
                colspan = int(td.get("colspan", 1))
            except ValueError:
                colspan = 1
            try:
                rowspan = int(td.get("rowspan", 1))
            except ValueError:
                rowspan = 1

            st = _style_map(td)
            shading = st.get("background-color") or st.get("background")
            if shading and shading.startswith("#"):
                shading = shading[1:].upper()
            elif shading:
                shading = shading.upper()

            nested = [
                t for t in td.find_all("table")
                if t.find_parent(["td", "th"]) is td
            ]

            borders = {}
            for k, v in td.attrs.items():
                if k.startswith("data-border-"):
                    borders[k[len("data-border-"):]] = v
            try:
                width = int(td.get("data-w")) if td.get("data-w") else None
            except ValueError:
                width = None

            # Alignment may sit on the cell or on the paragraph inside it.
            # An earlier version read only the cell and reported every centred
            # heading as lost -- a false finding against a product that had
            # preserved it correctly. Check both.
            align = st.get("text-align")
            if not align:
                first_p = td.find(["p", "div"], recursive=False)
                if first_p is not None:
                    align = _style_map(first_p).get("text-align")

            cell = Cell(
                row=r,
                col=c,
                row_span=rowspan,
                col_span=colspan,
                paragraphs=_html_cell_paragraphs(td),
                alignment=align,
                shading=shading,
                valign=st.get("vertical-align"),
                width_dxa=width,
                text_direction=td.get("data-dir"),
                borders=borders,
                nested=[_parse_html_table(t) for t in nested],
            )
            table.cells.append(cell)
            for rr in range(rowspan):
                for kk in range(colspan):
                    occupied[(r + rr, c + kk)] = cell
            c += colspan

    hr = tbl.get("data-header-rows")
    if hr:
        table.header_rows = [int(x) for x in hr.split(",") if x.strip()]
    elif tbl.find("thead") is not None:
        # A real <thead> is how the API expresses header rows. Reading it means
        # the HTML stage can distinguish "the header marking survived ingest and
        # was lost on export" from "it never arrived" -- which is the whole
        # value of a staged comparison.
        thead_rows = [tr for tr in tbl.find_all("tr")
                      if tr.find_parent("thead") is not None]
        all_rows = [tr for tr in tbl.find_all("tr") if tr.find_parent("table") is tbl]
        table.header_rows = [all_rows.index(tr) for tr in thead_rows
                             if tr in all_rows]
    table.layout = tbl.get("data-layout")
    cg = tbl.find("colgroup")
    if cg is not None and cg.find_parent("table") is tbl:
        for col in cg.find_all("col"):
            try:
                table.col_widths.append(int(col.get("data-w", 0)))
            except ValueError:
                table.col_widths.append(0)

    table.n_rows = max((c.row + c.row_span for c in table.cells), default=0)
    table.n_cols = max((c.col + c.col_span for c in table.cells), default=0)
    if table.col_widths:
        table.n_cols = max(table.n_cols, len(table.col_widths))
    return table


def from_html(html: str) -> Document:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    doc = Document()
    for tbl in soup.find_all("table"):
        if tbl.find_parent("table") is not None:
            continue  # nested tables are reached through their parent cell
        doc.tables.append(_parse_html_table(tbl))
    for p in soup.find_all(["p", "h1", "h2", "h3"]):
        if p.find_parent("table") is not None:
            continue
        txt = p.get_text().strip()
        if txt:
            doc.body_paragraphs.append(txt)
    return doc
