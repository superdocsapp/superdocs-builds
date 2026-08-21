"""Declarative table spec -> .docx.

Written against raw WordprocessingML rather than python-docx because the
benchmark needs exact control over vMerge, gridSpan, tblHeader and
textDirection -- the very constructs under test. A generator that could not
express a pathology could not test for it.
"""

from __future__ import annotations

import os
import zipfile
from xml.sax.saxutils import escape

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
</Types>"""

ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""

DOC_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""

STYLES = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="{W}">
<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/>
<w:sz w:val="20"/></w:rPr></w:rPrDefault></w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>
</w:styles>"""

DEFAULT_COL_DXA = 1800


def _p(text: str, align: str | None = None, bold: bool = False) -> str:
    ppr = f'<w:pPr><w:jc w:val="{align}"/></w:pPr>' if align else ""
    rpr = "<w:rPr><w:b/></w:rPr>" if bold else ""
    body = ""
    if text:
        body = (
            f'<w:r>{rpr}<w:t xml:space="preserve">{escape(text)}</w:t></w:r>'
        )
    elif bold:
        body = f"<w:r>{rpr}</w:r>"
    return f"<w:p>{ppr}{body}</w:p>"


def _tc_pr(cell: dict, span: int, vmerge: str | None, width: int) -> str:
    parts = [f'<w:tcW w:w="{width}" w:type="dxa"/>']
    if span > 1:
        parts.append(f'<w:gridSpan w:val="{span}"/>')
    if vmerge == "restart":
        parts.append('<w:vMerge w:val="restart"/>')
    elif vmerge == "continue":
        parts.append("<w:vMerge/>")
    if cell.get("fill"):
        parts.append(
            f'<w:shd w:val="clear" w:color="auto" w:fill="{cell["fill"].upper()}"/>'
        )
    if cell.get("valign"):
        parts.append(f'<w:vAlign w:val="{cell["valign"]}"/>')
    if cell.get("dir"):
        parts.append(f'<w:textDirection w:val="{cell["dir"]}"/>')
    if cell.get("borders"):
        edges = "".join(
            f'<w:{e} w:val="single" w:sz="{sz}" w:space="0" w:color="{col}"/>'
            for e, (sz, col) in cell["borders"].items()
        )
        parts.append(f"<w:tcBorders>{edges}</w:tcBorders>")
    return "<w:tcPr>" + "".join(parts) + "</w:tcPr>"


def _cell_body(cell: dict) -> str:
    out = []
    paras = cell.get("paragraphs")
    if paras is None:
        paras = [cell.get("text", "")]
    align = cell.get("align")
    bold = bool(cell.get("bold"))
    for text in paras:
        out.append(_p(text, align, bold))
    if cell.get("nested"):
        out.append(_table_xml(cell["nested"]))
        # OOXML requires a paragraph after a nested table inside a cell.
        out.append(_p(""))
    return "".join(out)


def _place(rows: list[list[dict]]):
    """Resolve the grid. Returns (placements, n_cols).

    placements[r] is an ordered list of (cell, col, span, vmerge).
    """
    occ: dict[tuple[int, int], dict] = {}
    for r, row in enumerate(rows):
        c = 0
        for cell in row:
            while (r, c) in occ:
                c += 1
            span = int(cell.get("colspan", 1))
            rspan = int(cell.get("rowspan", 1))
            cell["_r"], cell["_c"] = r, c
            for rr in range(rspan):
                for kk in range(span):
                    occ[(r + rr, c + kk)] = cell
            c += span

    n_rows = max((cell["_r"] + int(cell.get("rowspan", 1))
                  for row in rows for cell in row), default=0)
    n_cols = max((cell["_c"] + int(cell.get("colspan", 1))
                  for row in rows for cell in row), default=0)

    placements: list[list[tuple[dict, int, int, str | None]]] = []
    for r in range(n_rows):
        line = []
        c = 0
        while c < n_cols:
            cell = occ.get((r, c))
            if cell is None:
                c += 1
                continue
            if cell["_c"] != c:
                c += 1
                continue
            span = int(cell.get("colspan", 1))
            rspan = int(cell.get("rowspan", 1))
            if rspan > 1:
                vmerge = "restart" if cell["_r"] == r else "continue"
            else:
                vmerge = None
            line.append((cell, c, span, vmerge))
            c += span
        placements.append(line)
    return placements, n_cols


def _table_xml(spec: dict) -> str:
    rows = spec["rows"]
    placements, n_cols = _place(rows)
    widths = spec.get("col_widths") or [DEFAULT_COL_DXA] * n_cols
    total = sum(widths)

    grid = "".join(f'<w:gridCol w:w="{w}"/>' for w in widths)
    layout = spec.get("layout", "fixed")
    tbl_pr = (
        "<w:tblPr>"
        f'<w:tblW w:w="{total}" w:type="dxa"/>'
        f'<w:tblLayout w:type="{layout}"/>'
        "<w:tblBorders>"
        '<w:top w:val="single" w:sz="4" w:space="0" w:color="000000"/>'
        '<w:left w:val="single" w:sz="4" w:space="0" w:color="000000"/>'
        '<w:bottom w:val="single" w:sz="4" w:space="0" w:color="000000"/>'
        '<w:right w:val="single" w:sz="4" w:space="0" w:color="000000"/>'
        '<w:insideH w:val="single" w:sz="4" w:space="0" w:color="000000"/>'
        '<w:insideV w:val="single" w:sz="4" w:space="0" w:color="000000"/>'
        "</w:tblBorders>"
        "</w:tblPr>"
    )

    header_rows = set(spec.get("header_rows", []))
    body = []
    for r, line in enumerate(placements):
        tr_pr = "<w:trPr><w:tblHeader/></w:trPr>" if r in header_rows else ""
        tcs = []
        for cell, col, span, vmerge in line:
            width = sum(widths[col:col + span]) if col + span <= len(widths) else DEFAULT_COL_DXA
            if vmerge == "continue":
                inner = _p("")
            else:
                inner = _cell_body(cell)
            tcs.append(f"<w:tc>{_tc_pr(cell, span, vmerge, width)}{inner}</w:tc>")
        body.append(f"<w:tr>{tr_pr}{''.join(tcs)}</w:tr>")

    return f"<w:tbl>{tbl_pr}<w:tblGrid>{grid}</w:tblGrid>{''.join(body)}</w:tbl>"


def build_document_xml(case) -> str:
    parts = [_p(case.title, bold=True)]
    if case.intro:
        parts.append(_p(case.intro))
    for spec in case.tables:
        parts.append(_table_xml(spec))
        parts.append(_p(""))
    for tail in case.trailing_paragraphs:
        parts.append(_p(tail))
    sect = (
        '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
        '<w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134"/></w:sectPr>'
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{W}"><w:body>{"".join(parts)}{sect}</w:body></w:document>'
    )


def write_docx(case, out_path: str) -> str:
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    xml = build_document_xml(case)
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("_rels/.rels", ROOT_RELS)
        z.writestr("word/document.xml", xml)
        z.writestr("word/_rels/document.xml.rels", DOC_RELS)
        z.writestr("word/styles.xml", STYLES)
    return out_path
