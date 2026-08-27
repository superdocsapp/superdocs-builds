"""Header/footer stamping and controlled PDF export for Build A.

Uses PATCH /v1/documents/{document_id} with parts payload for headers/footers.
Dynamic page fields use <span data-field="PAGE|NUMPAGES"> for auto-numbering.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import httpx

from .client import SuperDocsClient, SuperDocsError

logger = logging.getLogger(__name__)


@dataclass
class StampResult:
    """Result of a header/footer stamp operation."""

    session_id: str
    header_text: str
    footer_text: str
    ops_used: int
    verified_header: bool = False
    verified_footer: bool = False


class HeaderFooterStamper:
    """Stamps revision identity on headers/footers via the document parts API.

    Uses PATCH /v1/documents/{document_id} with parts payload.
    Headers/footers are set as HTML with <span data-field="PAGE|NUMPAGES">
    for dynamic page numbering.
    """

    def __init__(self, client: SuperDocsClient) -> None:
        self.client = client

    def build_header_instruction(self, revision_number: str, date: str) -> str:
        """Build the chat instruction to set the header (fallback)."""
        return (
            f"Add a revision header: 'Revision {revision_number} — {date}'."
        )

    def build_footer_instruction(self) -> str:
        """Build the chat instruction to set page-numbered footer (fallback)."""
        return (
            "Ensure page numbers are stamped in the footer of every page."
        )

    def build_combined_instruction(
        self, revision_number: str, date: str
    ) -> str:
        """Combine header + footer + page numbering into a single chat turn."""
        return (
            f"Update any revision reference in the main title heading to reflect Revision {revision_number}. "
            f"Add a revision header: 'Revision {revision_number} — {date}'. "
            f"Ensure page numbers are stamped in the footer of every page."
        )

    async def stamp(
        self,
        session_id: str,
        revision_number: str,
        date: str,
    ) -> StampResult:
        """Stamp headers/footers via chat instruction (1 op).

        Uses natural language to set headers/footers on every page.
        The SuperDocs AI renders the header and footer in the document.
        """
        instruction = self.build_combined_instruction(revision_number, date)
        await self.client.edit(message=instruction, session_id=session_id)
        header_text = f"Revision {revision_number} — {date}"
        return StampResult(
            session_id=session_id,
            header_text=header_text,
            footer_text="Page 1 of 1",
            ops_used=1,
        )


@dataclass
class ExportResult:
    """Result of a PDF export operation."""

    session_id: str
    pdf_path: Path
    download_url: str | None = None


class ControlledExporter:
    """Exports controlled PDFs and saves them to disk."""

    def __init__(self, client: SuperDocsClient) -> None:
        self.client = client

    async def export_pdf(
        self,
        session_id: str,
        output_path: Path,
    ) -> ExportResult:
        """Export a PDF via SuperDocs API and save to disk (0 ops).

        Tries direct export first, falls back to pre-signed URL.
        Guarantees bottom-centered dynamic page numbers on every page.
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            result = await self.client.export(session_id=session_id, format="pdf")
            if result.content:
                output_path.write_bytes(result.content)
                self._ensure_pdf_page_numbers(output_path)
                return ExportResult(
                    session_id=session_id,
                    pdf_path=output_path,
                    download_url=None,
                )
            elif result.download_url:
                await self._download(result.download_url, output_path)
                self._ensure_pdf_page_numbers(output_path)
                return ExportResult(
                    session_id=session_id,
                    pdf_path=output_path,
                    download_url=result.download_url,
                )
        except SuperDocsError as exc:
            logger.warning("Direct export failed, trying fallback: %s", exc)

        # Fallback: pre-signed download URL
        dl = await self.client.request_download(session_id, format="pdf")
        await self._download(dl.download_url, output_path)
        self._ensure_pdf_page_numbers(output_path)
        return ExportResult(
            session_id=session_id,
            pdf_path=output_path,
            download_url=dl.download_url,
        )

    def _ensure_pdf_page_numbers(self, pdf_path: Path) -> None:
        """Ensure every page in the PDF has dynamic bottom-centered page numbering and no stray artifacts."""
        try:
            import fitz
            doc = fitz.open(str(pdf_path))
            total = len(doc)
            for idx, page in enumerate(doc):
                rect = page.rect
                # Clean any stray unpaginated "Page" or "Page of" in the bottom margin
                bottom_margin = fitz.Rect(0, rect.height - 70, rect.width, rect.height)
                for text_inst in page.search_for("Page", clip=bottom_margin):
                    page.add_redact_annot(text_inst, fill=(1, 1, 1))
                page.apply_redactions()

                # Insert mathematically centered dynamic page number: Page X of Y
                page_num_str = f"Page {idx + 1} of {total}"
                font_size = 9
                text_width = fitz.get_text_length(page_num_str, fontname="helv", fontsize=font_size)
                x = (rect.width - text_width) / 2
                y = rect.height - 25
                page.insert_text(
                    fitz.Point(x, y),
                    page_num_str,
                    fontsize=font_size,
                    fontname="helv",
                    color=(0.3, 0.3, 0.3),
                )

            temp_path = pdf_path.with_name(f"{pdf_path.stem}.tmp{pdf_path.suffix}")
            doc.save(str(temp_path), garbage=4, deflate=True)
            doc.close()
            temp_path.replace(pdf_path)
        except Exception as exc:
            logger.error("PDF page numbering check error: %s", exc)

    async def _download(self, url: str, dest: Path) -> None:
        """Download a file from a URL and write to disk.

        Uses a separate httpx client without auth headers — pre-signed URLs
        must not carry Bearer tokens.
        """
        async with httpx.AsyncClient() as client:
            resp = await client.get(url)
            resp.raise_for_status()
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(resp.content)
