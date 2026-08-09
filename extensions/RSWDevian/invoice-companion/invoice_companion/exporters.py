from __future__ import annotations

from html import escape
import io
import re
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile


def invoice_html(document: dict[str, Any]) -> str:
    fields = document["fields"]
    rows = "".join(
        "<tr>" + "".join(f"<td>{escape(str(row[field]))}</td>" for field in ("row_id", "description", "quantity", "unit_price", "line_total")) + "</tr>"
        for row in document["table"]
    )
    return (
        "<!doctype html><html><head><meta charset='utf-8'><title>Invoice "
        + escape(str(fields["invoice_id"]))
        + "</title><style>body{font-family:Arial,sans-serif;margin:48px}"
        "table{border-collapse:collapse;width:100%}th,td{border:1px solid #555;padding:8px;text-align:left}"
        ".total{font-size:1.2em;font-weight:bold}</style></head><body>"
        f"<h1>Invoice {escape(str(fields['invoice_id']))}</h1>"
        f"<p><strong>Seller:</strong> {escape(document['seller']['name'])}<br>"
        f"<strong>Buyer:</strong> {escape(document['buyer']['name'])}<br>"
        f"<strong>Issue date:</strong> {escape(str(fields['issue_date']))}<br>"
        f"<strong>Due date:</strong> {escape(str(fields['due_date']))}</p>"
        "<table><thead><tr><th>Row</th><th>Description</th><th>Quantity</th><th>Unit price</th><th>Line total</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
        f"<p>Subtotal: {escape(str(fields['currency']))} {escape(str(fields['subtotal']))}<br>"
        f"Tax: {escape(str(fields['currency']))} {escape(str(fields['tax']))}<br>"
        f"<span class='total'>Total: {escape(str(fields['currency']))} {escape(str(fields['total']))}</span><br>"
        f"Payment terms: {escape(str(fields['payment_terms']))}</p>"
        f"<p>{escape(str(document.get('narrative', '')))}</p></body></html>"
    )


def _xml_text(value: Any) -> str:
    return escape(str(value), quote=False)


def invoice_docx(document: dict[str, Any]) -> bytes:
    """Create a small valid Open XML document without third-party dependencies."""
    fields = document["fields"]
    paragraphs = [
        f"Invoice {fields['invoice_id']}",
        f"Seller: {document['seller']['name']}",
        f"Buyer: {document['buyer']['name']}",
        f"Issue date: {fields['issue_date']}    Due date: {fields['due_date']}",
        str(document.get("narrative", "")),
        f"Subtotal: {fields['currency']} {fields['subtotal']}    Tax: {fields['currency']} {fields['tax']}    Total: {fields['currency']} {fields['total']}",
        f"Payment terms: {fields['payment_terms']}",
    ]
    body = "".join(f"<w:p><w:r><w:t xml:space='preserve'>{_xml_text(text)}</w:t></w:r></w:p>" for text in paragraphs)
    header = ("<w:tbl><w:tblPr><w:tblBorders><w:top w:val='single'/><w:left w:val='single'/><w:bottom w:val='single'/><w:right w:val='single'/><w:insideH w:val='single'/><w:insideV w:val='single'/></w:tblBorders></w:tblPr><w:tr>"
              + "".join(f"<w:tc><w:p><w:r><w:t>{_xml_text(label)}</w:t></w:r></w:p></w:tc>" for label in ("Row", "Description", "Quantity", "Unit price", "Line total"))
              + "</w:tr>")
    table = header + "".join(
        "<w:tr>" + "".join(f"<w:tc><w:p><w:r><w:t>{_xml_text(row[field])}</w:t></w:r></w:p></w:tc>" for field in ("row_id", "description", "quantity", "unit_price", "line_total")) + "</w:tr>"
        for row in document["table"]
    ) + "</w:tbl>"
    document_xml = ("<?xml version='1.0' encoding='UTF-8' standalone='yes'?><w:document xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'>"
                    f"<w:body>{body}{table}<w:sectPr/></w:body></w:document>")
    content_types = ("<?xml version='1.0' encoding='UTF-8' standalone='yes'?><Types xmlns='http://schemas.openxmlformats.org/package/2006/content-types'>"
                     "<Default Extension='rels' ContentType='application/vnd.openxmlformats-package.relationships+xml'/><Default Extension='xml' ContentType='application/xml'/><Override PartName='/word/document.xml' ContentType='application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml'/></Types>")
    relationships = ("<?xml version='1.0' encoding='UTF-8' standalone='yes'?><Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'>"
                     "<Relationship Id='rId1' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument' Target='word/document.xml'/></Relationships>")
    output = io.BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", relationships)
        archive.writestr("word/document.xml", document_xml)
    return output.getvalue()


def _pdf_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def invoice_pdf(document: dict[str, Any]) -> bytes:
    """Create a dependency-free, readable one-page PDF for local/offline use."""
    fields = document["fields"]
    lines = [
        f"Invoice {fields['invoice_id']}",
        f"Seller: {document['seller']['name']}",
        f"Buyer: {document['buyer']['name']}",
        f"Issue: {fields['issue_date']}  Due: {fields['due_date']}",
        "",
        "Row  Description                 Qty  Unit       Total",
    ]
    lines += [f"{row['row_id']}  {str(row['description'])[:25]:25}  {row['quantity']:>3}  {row['unit_price']:>8}  {row['line_total']:>8}" for row in document["table"]]
    lines += ["", f"Subtotal: {fields['currency']} {fields['subtotal']}", f"Tax: {fields['currency']} {fields['tax']}", f"TOTAL: {fields['currency']} {fields['total']}", f"Terms: {fields['payment_terms']}"]
    stream = "BT\n/F1 10 Tf\n50 760 Td\n" + "\n".join(f"({_pdf_escape(line)}) Tj\n0 -16 Td" for line in lines) + "\nET\n"
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


def export_bytes(document: dict[str, Any], format_name: str) -> tuple[str, bytes]:
    if format_name == "html":
        return "text/html", invoice_html(document).encode()
    if format_name == "docx":
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document", invoice_docx(document)
    if format_name == "pdf":
        return "application/pdf", invoice_pdf(document)
    if format_name == "json":
        import json
        return "application/json", json.dumps(document, sort_keys=True, indent=2).encode()
    raise ValueError("format must be json, html, docx, or pdf")
