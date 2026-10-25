from __future__ import annotations

from html import escape
import io
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

from .model import Manual


DISCLAIMER = "Review-ready draft - not ISO certified"


def manual_html(manual: Manual) -> str:
    sections = []
    for section in manual.sections:
        steps = "".join(f"<li data-step-id='{escape(block['step_id'])}'><strong>{escape(block['step_id'])}</strong> {escape(block['text'])}</li>" for block in section["body_blocks"] if block.get("type") == "step")
        diagram = next((item for item in manual.diagrams if item.diagram_id == section.get("diagram_ref")), None)
        source = escape(diagram.source_text if diagram else "")
        sections.append(f"<section><h2>{escape(section['title'])}</h2><p>Clause {escape(section['clause_ref'])}</p><ol>{steps}</ol><h3>Process diagram</h3><pre>{source}</pre></section>")
    return f"<!doctype html><html><head><meta charset='utf-8'><title>{escape(manual.title)}</title><style>body{{font-family:Arial;margin:48px}}pre{{background:#f2f4f3;padding:16px;white-space:pre-wrap}}.disclaimer{{border:1px solid #d77;padding:10px}}</style></head><body><h1>{escape(manual.title)}</h1><p>{escape(manual.organization)} | Revision {manual.revision}</p><p class='disclaimer'>{DISCLAIMER}</p>{''.join(sections)}</body></html>"


def manual_docx(manual: Manual) -> bytes:
    paragraphs = [f"{manual.title} - Revision {manual.revision}", manual.organization, DISCLAIMER]
    for section in manual.sections:
        paragraphs.append(f"{section['clause_ref']} {section['title']}")
        paragraphs.extend(f"{block['step_id']}: {block['text']}" for block in section["body_blocks"] if block.get("type") == "step")
        diagram = next(item for item in manual.diagrams if item.diagram_id == section["diagram_ref"])
        paragraphs.append(f"Diagram source ({diagram.diagram_id}):\n{diagram.source_text}")
    body = "".join(f"<w:p><w:r><w:t xml:space='preserve'>{escape(text, quote=False)}</w:t></w:r></w:p>" for text in paragraphs)
    document = f"<?xml version='1.0' encoding='UTF-8' standalone='yes'?><w:document xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'><w:body>{body}<w:sectPr/></w:body></w:document>"
    types = "<?xml version='1.0' encoding='UTF-8' standalone='yes'?><Types xmlns='http://schemas.openxmlformats.org/package/2006/content-types'><Default Extension='rels' ContentType='application/vnd.openxmlformats-package.relationships+xml'/><Default Extension='xml' ContentType='application/xml'/><Override PartName='/word/document.xml' ContentType='application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml'/></Types>"
    rels = "<?xml version='1.0' encoding='UTF-8' standalone='yes'?><Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'><Relationship Id='rId1' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument' Target='word/document.xml'/></Relationships>"
    output = io.BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", types)
        archive.writestr("_rels/.rels", rels)
        archive.writestr("word/document.xml", document)
    return output.getvalue()


def manual_pdf(manual: Manual) -> bytes:
    lines = [manual.title, f"{manual.organization} | Revision {manual.revision}", DISCLAIMER, ""]
    for section in manual.sections:
        lines.append(f"{section['clause_ref']} {section['title']}")
        lines.extend(f"{block['step_id']}: {block['text']}" for block in section["body_blocks"] if block.get("type") == "step")
        lines.append("")
    stream = "BT\n/F1 10 Tf\n50 760 Td\n" + "\n".join(f"({line.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')}) Tj\n0 -16 Td" for line in lines) + "\nET\n"
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>", b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>", b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>", f"<< /Length {len(stream.encode())} >>\nstream\n{stream}endstream".encode()]
    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(pdf)); pdf.extend(f"{index} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = len(pdf); pdf.extend(f"xref\n0 {len(objects)+1}\n0000000000 65535 f \n".encode()); pdf.extend("".join(f"{offset:010d} 00000 n \n" for offset in offsets[1:]).encode()); pdf.extend(f"trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return bytes(pdf)


def export_bytes(manual: Manual, format_name: str) -> tuple[str, bytes]:
    if format_name == "html": return "text/html", manual_html(manual).encode()
    if format_name == "docx": return "application/vnd.openxmlformats-officedocument.wordprocessingml.document", manual_docx(manual)
    if format_name == "pdf": return "application/pdf", manual_pdf(manual)
    if format_name == "json": return "application/json", __import__("json").dumps(manual.to_dict(), sort_keys=True, indent=2).encode()
    raise ValueError("format must be json, html, docx, or pdf")
