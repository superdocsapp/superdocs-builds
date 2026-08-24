"""Deterministic Northgate Medical Devices letterhead DOCX (pure stdlib).

Generates the branded letterhead template uploaded once via
POST /v1/templates/upload so every generated audit-readiness pack inherits
its page header, footer and styling. Byte-identical output per run.
"""

import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

BRAND = "0F5E5B"
OUT = Path(__file__).resolve().parent.parent / "assets" / \
    "northgate-letterhead.docx"

CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
<Override PartName="/word/header1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"/>
<Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>
<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>"""

ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>"""

DOC_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/header" Target="header1.xml"/>
<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer1.xml"/>
</Relationships>"""

STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/><w:sz w:val="22"/></w:rPr></w:rPrDefault></w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>
</w:styles>"""

APP_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"><Application>clausekeeper synthetic template generator</Application></Properties>"""

CORE_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
<dc:title>Northgate Medical Devices letterhead</dc:title>
<dc:creator>Northgate Medical Devices (synthetic demo company)</dc:creator>
<cp:lastModifiedBy>clausekeeper</cp:lastModifiedBy>
<dcterms:created xsi:type="dcterms:W3CDTF">2026-08-01T00:00:00Z</dcterms:created>
<dcterms:modified xsi:type="dcterms:W3CDTF">2026-08-01T00:00:00Z</dcterms:modified>
</cp:coreProperties>"""

HEADER_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<w:hdr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
    '<w:p><w:pPr><w:pBdr><w:bottom w:val="single" w:sz="18" w:space="4"'
    f' w:color="{BRAND}"/></w:pBdr><w:spacing w:after="120"/></w:pPr>'
    '<w:r><w:rPr><w:b/><w:color w:val="' + BRAND + '"/>'
    '<w:sz w:val="40"/></w:rPr>'
    '<w:t xml:space="preserve">NORTHGATE MEDICAL DEVICES</w:t></w:r></w:p>'
    '<w:p><w:pPr><w:spacing w:after="240"/></w:pPr>'
    '<w:r><w:rPr><w:i/><w:color w:val="555555"/><w:sz w:val="18"/></w:rPr>'
    '<w:t xml:space="preserve">Quality Management System &#183; 400 Foundry'
    ' Park Drive, Marlowe Heights, OH 44101 &#183; Template QMS-LH-01'
    '</w:t></w:r></w:p>'
    '</w:hdr>')

FOOTER_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<w:ftr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
    '<w:p><w:pPr><w:pBdr><w:top w:val="single" w:sz="12" w:space="4"'
    f' w:color="{BRAND}"/></w:pBdr><w:jc w:val="center"/></w:pPr>'
    '<w:r><w:rPr><w:color w:val="777777"/><w:sz w:val="16"/></w:rPr>'
    '<w:t xml:space="preserve">Synthetic demo corpus &#8212; Northgate'
    ' Medical Devices is a fictional company. Internal readiness use'
    ' only.</w:t></w:r></w:p>'
    '</w:ftr>')


def _run(text, bold=False, italic=False, color=None, size=None):
    rpr = "<w:rPr>" + ("<w:b/>" if bold else "") + \
        ("<w:i/>" if italic else "") + \
        (f'<w:color w:val="{color}"/>' if color else "") + \
        (f'<w:sz w:val="{size}"/>' if size else "") + "</w:rPr>"
    return f"<w:r>{rpr}<w:t xml:space=\"preserve\">{escape(text)}</w:t></w:r>"


def _para(runs, spacing_after=80, jc=None):
    pr = f'<w:spacing w:after="{spacing_after}"/>'
    if jc:
        pr += f'<w:jc w:val="{jc}"/>'
    return f"<w:p><w:pPr>{pr}</w:pPr>{''.join(runs)}</w:p>"


def document_xml():
    parts = [
        _para([_run("Document Control Letterhead", bold=True, color=BRAND,
                    size=32)], spacing_after=240, jc="center"),
        _para([_run("This template carries Northgate Medical Devices"
                    " branding on its default page header and footer.",
                    italic=True, color="555555")], spacing_after=240,
              jc="center"),
        _para([_run("Purpose", bold=True, color=BRAND, size=26)]),
        _para([_run("Generated deliverables - audit-readiness packs,"
                    " traceability matrices, summary pages - inherit this"
                    " header, footer and palette so every pack reads as an"
                    " internal Northgate document.")]),
        _para([_run("Branding elements", bold=True, color=BRAND, size=26)]),
        _table(),
        _para([_run("Northgate Medical Devices is a fictional demo company;"
                    " nothing here describes a real manufacturer.")],
              spacing_after=0),
    ]
    sect = ('<w:sectPr>'
            '<w:headerReference w:type="default" r:id="rId2"/>'
            '<w:footerReference w:type="default" r:id="rId3"/>'
            '<w:pgSz w:w="11906" w:h="16838"/>'
            '<w:pgMar w:top="1134" w:right="1134" w:bottom="1134"'
            ' w:left="1134"/>'
            '</w:sectPr>')
    body = "".join(parts) + sect
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/'
        'wordprocessingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/'
        'relationships">'
        f"<w:body>{body}</w:body></w:document>"
    )


def _table():
    border = ("<w:tblBorders>" + "".join(
        f'<w:{side} w:val="single" w:sz="4" w:space="0" w:color="{BRAND}"/>'
        for side in ("top", "left", "bottom", "right", "insideH",
                     "insideV")) + "</w:tblBorders>")
    rows = [
        ("Element", "Value"),
        ("Company", "Northgate Medical Devices"),
        ("Palette", "Teal #0F5E5B on white"),
        ("Header rule", "Single 2.25pt teal underline"),
        ("Footer note", "Fictional-company disclosure"),
    ]
    trs = []
    for i, row in enumerate(rows):
        cells = []
        for cell in row:
            runs = [_run(cell, bold=(i == 0),
                         color=BRAND if i == 0 else None)]
            cells.append(
                "<w:tc><w:tcPr>"
                "<w:tcW w:w=\"0\" w:type=\"auto\"/></w:tcPr>"
                f"<w:p>{''.join(runs)}</w:p></w:tc>")
        trs.append(f"<w:tr>{''.join(cells)}</w:tr>")
    return (f"<w:tbl><w:tblPr>{border}</w:tblPr>{''.join(trs)}</w:tbl>"
            "<w:p/>")


def build(path: Path = OUT) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    entries = [
        ("[Content_Types].xml", CONTENT_TYPES),
        ("_rels/.rels", ROOT_RELS),
        ("word/document.xml", document_xml()),
        ("word/_rels/document.xml.rels", DOC_RELS),
        ("word/styles.xml", STYLES),
        ("word/header1.xml", HEADER_XML),
        ("word/footer1.xml", FOOTER_XML),
        ("docProps/core.xml", CORE_XML),
        ("docProps/app.xml", APP_XML),
    ]
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in entries:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            info.create_system = 0
            info.external_attr = 0
            zf.writestr(info, data.encode("utf-8"))
    return path


if __name__ == "__main__":
    print(build())
