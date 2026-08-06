"""Export facade for Interview Preparation Report formats."""

from __future__ import annotations

from app.schemas.report import ExportFormat, InterviewPreparationReportDocument
from app.services.report.exporters.common import safe_filename
from app.services.report.exporters.docx_exporter import to_docx_bytes
from app.services.report.exporters.html_exporter import to_html
from app.services.report.exporters.markdown_exporter import to_markdown
from app.services.report.exporters.pdf_exporter import to_pdf_bytes


CONTENT_TYPES = {
    ExportFormat.MARKDOWN: "text/markdown; charset=utf-8",
    ExportFormat.HTML: "text/html; charset=utf-8",
    ExportFormat.DOCX: (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ),
    ExportFormat.PDF: "application/pdf",
    ExportFormat.JSON: "application/json; charset=utf-8",
}


class ReportExporter:
    def export(
        self,
        report: InterviewPreparationReportDocument,
        fmt: ExportFormat,
    ) -> tuple[bytes, str, str]:
        """
        Returns (payload_bytes, content_type, filename).
        """
        company = report.cover_page.company_name

        if fmt == ExportFormat.MARKDOWN:
            data = to_markdown(report).encode("utf-8")
            return data, CONTENT_TYPES[fmt], safe_filename(company, "md")

        if fmt == ExportFormat.HTML:
            data = to_html(report).encode("utf-8")
            return data, CONTENT_TYPES[fmt], safe_filename(company, "html")

        if fmt == ExportFormat.DOCX:
            return to_docx_bytes(report), CONTENT_TYPES[fmt], safe_filename(company, "docx")

        if fmt == ExportFormat.PDF:
            return to_pdf_bytes(report), CONTENT_TYPES[fmt], safe_filename(company, "pdf")

        if fmt == ExportFormat.JSON:
            data = report.model_dump_json(indent=2).encode("utf-8")
            return data, CONTENT_TYPES[fmt], safe_filename(company, "json")

        raise ValueError(f"Unsupported export format: {fmt}")
