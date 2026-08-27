from __future__ import annotations

from html import escape
import io
import json
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

from .core import Patent

DISCLAIMER = "Draft for attorney review - not a filed or certified document"


def patent_html(patent: Patent) -> str:
    rows = []
    for claim in patent.claims.as_list():
        depends = ", ".join(str(number) for number in claim["depends_on"]) or "-"
        rows.append(
            "<tr>"
            f"<td>{claim['number']}</td><td>{escape(claim['kind'])}</td><td>{depends}</td>"
            f"<td>{escape(claim['text'])}</td>"
            "</tr>"
        )
    history = "".join(
        f"<li>Rev {entry['revision']}: {escape(str(entry.get('action', '')))} claim {entry.get('claim_number')}"
        f" by {escape(str(entry.get('author', '')))}"
        + (f" - flags claim(s) {', '.join(str(n) for n in entry['flagged_dependents'])} for review" if entry.get("flagged_dependents") else "")
        + "</li>"
        for entry in patent.revision_history
    )
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{escape(patent.title)}</title>"
        "<style>body{font-family:Arial;margin:48px}table{border-collapse:collapse;width:100%}"
        "td,th{border:1px solid #bbb;padding:8px;text-align:left;vertical-align:top}"
        ".disclaimer{border:1px solid #d77;padding:10px}</style></head><body>"
        f"<h1>{escape(patent.title)}</h1><p>{escape(patent.applicant)} | Revision {patent.revision}</p>"
        f"<p class='disclaimer'>{DISCLAIMER}</p>"
        "<table><thead><tr><th>Claim</th><th>Kind</th><th>Depends on</th><th>Text</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
        f"<h2>Revision history</h2><ul>{history}</ul>"
        "</body></html>"
    )


def patent_docx(patent: Patent) -> bytes:
    paragraphs = [f"{patent.title} - Revision {patent.revision}", patent.applicant, DISCLAIMER]
    for claim in patent.claims.as_list():
        depends = ", ".join(str(number) for number in claim["depends_on"]) or "none"
        paragraphs.append(f"{claim['number']}. ({claim['kind']}, depends on: {depends}) {claim['text']}")
    body = "".join(f"<w:p><w:r><w:t xml:space='preserve'>{escape(text, quote=False)}</w:t></w:r></w:p>" for text in paragraphs)
    document = (
        "<?xml version='1.0' encoding='UTF-8' standalone='yes'?>"
        "<w:document xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'>"
        f"<w:body>{body}<w:sectPr/></w:body></w:document>"
    )
    types = (
        "<?xml version='1.0' encoding='UTF-8' standalone='yes'?>"
        "<Types xmlns='http://schemas.openxmlformats.org/package/2006/content-types'>"
        "<Default Extension='rels' ContentType='application/vnd.openxmlformats-package.relationships+xml'/>"
        "<Default Extension='xml' ContentType='application/xml'/>"
        "<Override PartName='/word/document.xml' ContentType='application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml'/>"
        "</Types>"
    )
    rels = (
        "<?xml version='1.0' encoding='UTF-8' standalone='yes'?>"
        "<Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'>"
        "<Relationship Id='rId1' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument' Target='word/document.xml'/>"
        "</Relationships>"
    )
    output = io.BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", types)
        archive.writestr("_rels/.rels", rels)
        archive.writestr("word/document.xml", document)
    return output.getvalue()


def patent_pdf(patent: Patent) -> bytes:
    lines = [patent.title, f"{patent.applicant} | Revision {patent.revision}", DISCLAIMER, ""]
    for claim in patent.claims.as_list():
        depends = ", ".join(str(number) for number in claim["depends_on"]) or "none"
        lines.append(f"{claim['number']}. ({claim['kind']}, depends on: {depends}) {claim['text']}")

    def escape_pdf_text(line: str) -> str:
        return line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    stream = "BT\n/F1 10 Tf\n50 760 Td\n" + "\n".join(f"({escape_pdf_text(line)}) Tj\n0 -16 Td" for line in lines) + "\nET\n"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Length {len(stream.encode())} >>\nstream\n{stream}endstream".encode(),
    ]
    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(pdf))
        pdf.extend(f"{index} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    pdf.extend("".join(f"{offset:010d} 00000 n \n" for offset in offsets[1:]).encode())
    pdf.extend(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return bytes(pdf)


def export_bytes(patent: Patent, format_name: str) -> tuple[str, bytes]:
    if format_name == "json":
        return "application/json", json.dumps(patent.to_dict(), sort_keys=True, indent=2).encode()
    if format_name == "html":
        return "text/html", patent_html(patent).encode()
    if format_name == "docx":
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document", patent_docx(patent)
    if format_name == "pdf":
        return "application/pdf", patent_pdf(patent)
    raise ValueError("format must be json, html, docx, or pdf")
