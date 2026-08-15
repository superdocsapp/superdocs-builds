"""
RECIPE 3 — Export an approved document in multiple formats.

Flow (matches the brief exactly):
    approved document (session_id, already committed/approved by recipes 1/2)
    -> export DOCX
    -> export PDF
    -> optionally export Markdown/TXT
    -> return typed artifacts

Chosen failure behavior, stated explicitly per the brief's own instruction
("choose a sensible behavior and document it"):

    CONTINUE OTHER EXPORTS, DO NOT FAIL ATOMICALLY.

Rationale: the four export calls are independent SuperDocs operations against
the same already-committed document -- one format failing (e.g. a PDF
rendering edge case) has no bearing on whether DOCX or Markdown will succeed,
and an "all or nothing" recipe would throw away three good artifacts because
of one unrelated failure. Each export's outcome (success + ExportOutput, or
failure + the typed error) is reported independently in
MultiFormatExportOutput, so the platform can decide what to do with a partial
result -- retry just the failed format, proceed with what it has, or alert a
human -- rather than the connector making that call unilaterally.

This recipe does NOT retry failed exports itself: retries for retryable
statuses (429/500/504) already happened inside export_document's underlying
HTTP call (the connector's standard retry contract); if it still failed after
that, retrying the exact same request again at the recipe level is unlikely
to help and this recipe reports the failure instead of masking it with a
second retry layer.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from connector.errors import SuperDocsConnectorError
from connector.http_client import SuperDocsHTTPClient
from connector.operations.export_document import export_document
from schemas.common import ExportFormat
from schemas.export import ExportInput, ExportOutput


@dataclass
class MultiFormatExportInput:
    session_id: str
    formats: list[ExportFormat] = field(default_factory=lambda: [ExportFormat.docx, ExportFormat.pdf])


@dataclass
class FormatExportResult:
    format: ExportFormat
    success: bool
    output: ExportOutput | None = None
    error_type: str | None = None
    error_message: str | None = None
    retryable: bool | None = None


@dataclass
class MultiFormatExportOutput:
    session_id: str
    results: list[FormatExportResult]

    @property
    def all_succeeded(self) -> bool:
        return all(r.success for r in self.results)

    @property
    def succeeded_formats(self) -> list[ExportFormat]:
        return [r.format for r in self.results if r.success]


async def run_recipe_3(client: SuperDocsHTTPClient, recipe_input: MultiFormatExportInput) -> MultiFormatExportOutput:
    results: list[FormatExportResult] = []

    for fmt in recipe_input.formats:
        try:
            output = await export_document(client, ExportInput(session_id=recipe_input.session_id, format=fmt))
            results.append(FormatExportResult(format=fmt, success=True, output=output))
        except SuperDocsConnectorError as exc:
            # Continue to the next format rather than aborting the whole
            # recipe -- see module docstring for the reasoning.
            results.append(FormatExportResult(
                format=fmt, success=False,
                error_type=type(exc).__name__, error_message=str(exc), retryable=exc.retryable,
            ))

    return MultiFormatExportOutput(session_id=recipe_input.session_id, results=results)
