"""
export_document — wraps POST /v1/documents/export.

Handles the binary response body, extracts the filename from
Content-Disposition, and best-effort-decodes X-Export-Warnings into typed
ExportWarningEntry objects (see _extract_warnings' docstring for the honest
caveat on that header's undocumented exact wire encoding). Per the brief and
the SuperDocs docs: warnings are non-fatal — an export with warnings is still
success, never raised as an error.
"""
from __future__ import annotations

import base64
import json
import re

from connector.http_client import SuperDocsHTTPClient
from schemas.export import ExportInput, ExportOutput, ExportWarningEntry

_FILENAME_RE = re.compile(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?')


def _extract_filename(content_disposition: str | None) -> str | None:
    if not content_disposition:
        return None
    match = _FILENAME_RE.search(content_disposition)
    return match.group(1) if match else None


def _extract_warnings(header_value: str | None) -> list[ExportWarningEntry]:
    """
    Parses the X-Export-Warnings header. IMPORTANT HONESTY NOTE: the docs
    (docs.superdocs.app) document this header's *existence* and that it's
    non-fatal, but not its exact wire encoding. This connector defends
    against two plausible encodings without asserting either is "the"
    documented one: (1) base64-encoded JSON array, (2) plain JSON array. If
    neither parses, the raw header text is preserved as a single warning
    entry's `message` rather than silently discarded -- so a real warning is
    never lost even if the encoding assumption above turns out to be wrong,
    and this is called out explicitly in the README's limitations section.
    """
    if not header_value:
        return []
    for decode in (lambda v: base64.b64decode(v).decode("utf-8"), lambda v: v):
        try:
            raw_list = json.loads(decode(header_value))
            if isinstance(raw_list, list):
                return [ExportWarningEntry(**w) if isinstance(w, dict) else ExportWarningEntry(code="warning", message=str(w))
                         for w in raw_list]
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError, TypeError):
            continue
    # Neither decoding worked -- preserve the raw text rather than drop it.
    return [ExportWarningEntry(code="unparsed", message=header_value)]


def _build_request_body(input: ExportInput) -> dict:
    body: dict = {"format": input.format.value}
    if input.html is not None:
        body["html"] = input.html
    if input.session_id is not None:
        body["session_id"] = input.session_id
    if input.upload_id is not None:
        body["upload_id"] = input.upload_id
    if input.filename is not None:
        body["filename"] = input.filename
    if input.options is not None:
        body["options"] = input.options.model_dump(exclude_none=True)
    return body


async def export_document(client: SuperDocsHTTPClient, input: ExportInput) -> ExportOutput:
    body = _build_request_body(input)
    response = await client.post_binary("/v1/documents/export", body)

    warnings = _extract_warnings(response.headers.get("X-Export-Warnings"))
    filename = _extract_filename(response.headers.get("Content-Disposition")) or input.filename

    return ExportOutput(
        format=input.format,
        filename=filename,
        content_type=response.headers.get("Content-Type", "application/octet-stream"),
        content_base64=base64.b64encode(response.content).decode("ascii"),
        size_bytes=len(response.content),
        warnings=warnings,
    )
