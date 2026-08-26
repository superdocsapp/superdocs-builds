"""The pipeline end to end: a OneNote page -> reading-order HTML -> a branded,
exportable SuperDocs document.

    OneNote(Graph) --page_html--> relinearize --clean html--> SuperDocs --> .docx

Both clients are injectable, so `export_page` is testable without Microsoft or a key.
"""
from __future__ import annotations

from relinearize import to_reading_order_html


def export_page(onenote, superdocs, page_id: str, title: str = "",
                session_id: str = "onenote-export", fmt: str = "docx") -> dict:
    raw = onenote.page_html(page_id)
    html = to_reading_order_html(raw, title)
    superdocs.send_document(
        html, session_id,
        instruction="Produce a clean branded document with headings and paragraphs intact.")
    docx = superdocs.export(session_id, fmt)
    return {"page_id": page_id, "html": html, "docx_bytes": len(docx)}
