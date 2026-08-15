import base64
import json

import httpx
import pytest

from connector.operations.export_document import export_document
from schemas.common import ExportFormat
from schemas.export import ExportInput


def _binary_response(content: bytes, content_type: str, filename: str, warnings_header: str | None = None) -> httpx.Response:
    headers = {"Content-Type": content_type, "Content-Disposition": f'attachment; filename="{filename}"'}
    if warnings_header is not None:
        headers["X-Export-Warnings"] = warnings_header
    return httpx.Response(200, content=content, headers=headers)


@pytest.mark.asyncio
async def test_raw_binary_response_is_not_treated_as_json(fake_server, client):
    fake_bytes = b"\x50\x4b\x03\x04fake-docx-zip-bytes"  # not valid JSON
    fake_server.on("POST", "/v1/documents/export",
                    lambda r: _binary_response(fake_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "out.docx"))

    result = await export_document(client, ExportInput(session_id="s1", format=ExportFormat.docx))

    assert base64.b64decode(result.content_base64) == fake_bytes
    assert result.size_bytes == len(fake_bytes)


@pytest.mark.asyncio
async def test_filename_and_content_type_extracted_from_headers(fake_server, client):
    fake_server.on("POST", "/v1/documents/export",
                    lambda r: _binary_response(b"pdfbytes", "application/pdf", "quarterly-report.pdf"))

    result = await export_document(client, ExportInput(session_id="s1", format=ExportFormat.pdf))

    assert result.filename == "quarterly-report.pdf"
    assert result.content_type == "application/pdf"


@pytest.mark.asyncio
async def test_x_export_warnings_header_parsed_as_base64_json(fake_server, client):
    warnings_payload = [{"code": "image_download_failed", "message": "One remote image could not be fetched"}]
    encoded = base64.b64encode(json.dumps(warnings_payload).encode()).decode()
    fake_server.on("POST", "/v1/documents/export",
                    lambda r: _binary_response(b"docbytes", "application/pdf", "out.pdf", warnings_header=encoded))

    result = await export_document(client, ExportInput(session_id="s1", format=ExportFormat.pdf))

    assert len(result.warnings) == 1
    assert result.warnings[0].code == "image_download_failed"
    # Warnings must never turn a successful export into an error -- there's
    # no exception here, just informational data on a 200 response.


@pytest.mark.asyncio
async def test_x_export_warnings_header_parsed_as_plain_json_fallback(fake_server, client):
    """Defends the second plausible encoding, since the docs don't pin down
    the exact wire format for this header (see _extract_warnings)."""
    plain = json.dumps([{"code": "font_substituted", "message": "Calibri unavailable, used Arial"}])
    fake_server.on("POST", "/v1/documents/export",
                    lambda r: _binary_response(b"docbytes", "application/pdf", "out.pdf", warnings_header=plain))

    result = await export_document(client, ExportInput(session_id="s1", format=ExportFormat.pdf))
    assert result.warnings[0].code == "font_substituted"


@pytest.mark.asyncio
async def test_missing_warnings_header_yields_empty_list(fake_server, client):
    fake_server.on("POST", "/v1/documents/export",
                    lambda r: _binary_response(b"bytes", "text/plain", "out.txt"))
    result = await export_document(client, ExportInput(session_id="s1", format=ExportFormat.txt))
    assert result.warnings == []


@pytest.mark.parametrize("fmt,content_type", [
    (ExportFormat.docx, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    (ExportFormat.pdf, "application/pdf"),
    (ExportFormat.html, "text/html"),
    (ExportFormat.markdown, "text/markdown"),
    (ExportFormat.txt, "text/plain"),
])
@pytest.mark.asyncio
async def test_all_five_supported_formats(fake_server, client, fmt, content_type):
    def handler(request):
        sent = json.loads(request.content)
        assert sent["format"] == fmt.value
        return _binary_response(b"content-for-" + fmt.value.encode(), content_type, f"out.{fmt.value}")

    fake_server.on("POST", "/v1/documents/export", handler)
    result = await export_document(client, ExportInput(session_id="s1", format=fmt))
    assert result.format == fmt
    assert result.content_type == content_type


def test_export_input_requires_exactly_one_source():
    with pytest.raises(Exception, match="exactly one"):
        ExportInput(html="<p>x</p>", session_id="s1", format=ExportFormat.pdf)
    with pytest.raises(Exception, match="exactly one"):
        ExportInput(format=ExportFormat.pdf)
