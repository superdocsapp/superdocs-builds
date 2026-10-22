from __future__ import annotations

import json

import httpx
import pytest

from redline.superdocs.client import SuperDocsClient
from redline.superdocs.transport import HTTPTransport, SuperDocsAPIError

API_KEY = "sk_test_not_a_real_key"


def _client(handler) -> SuperDocsClient:
    """A SuperDocsClient wired to a mock HTTP server.

    This exercises the REAL HTTPTransport -- headers, JSON encoding, status handling --
    without a live key or network. FakeSuperDocs replaces the transport entirely, so it
    can never catch a bug in how we actually speak HTTP; this test can.
    """
    mock = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return SuperDocsClient(HTTPTransport("https://api.superdocs.app", API_KEY, client=mock))


async def test_requests_carry_bearer_auth_and_documented_payload_shapes():
    seen: list[tuple[str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("authorization") == f"Bearer {API_KEY}"
        body = json.loads(request.content) if request.content else {}
        seen.append((request.url.path, body))
        if request.url.path == "/v1/documents/upload-base64":
            return httpx.Response(
                200,
                json={
                    "session_id": body["session_id"],
                    "document_id": "doc_9",
                    "chunks_count": 3,
                    "version_id": "v1",
                },
            )
        if request.url.path == "/v1/chat/async":
            return httpx.Response(200, json={"job_id": "job_x"})
        raise AssertionError(f"unexpected path {request.url.path}")

    client = _client(handler)
    upload = await client.upload_document(
        "MSA.docx", b"contract bytes", session_id="s1", open_mode="background"
    )
    assert upload.document_id == "doc_9"
    assert upload.session_id == "s1"

    job_id = await client.start_edit(
        "s1", "cap liability", document_id="doc_9", cross_session_search=True
    )
    assert job_id == "job_x"

    upload_body = dict(seen)["/v1/documents/upload-base64"]
    assert upload_body["open_mode"] == "background"
    assert "file_base64" in upload_body
    chat_body = dict(seen)["/v1/chat/async"]
    assert chat_body["document_id"] == "doc_9"
    assert chat_body["cross_session_search"] is True


async def test_session_documents_are_parsed_from_the_documented_shape():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/sessions/s1/documents"
        return httpx.Response(
            200,
            json={
                "documents": [
                    {
                        "document_id": "doc_1",
                        "title": "MSA.docx",
                        "is_focused": True,
                        "sections_count": 12,
                    },
                    {"document_id": "doc_2", "title": "Amendment.docx", "is_focused": False},
                ],
                "focused_document_id": "doc_1",
            },
        )

    documents = await _client(handler).list_session_documents("s1")
    assert [d.document_id for d in documents] == ["doc_1", "doc_2"]
    assert documents[0].is_focused is True
    assert documents[1].is_focused is False


async def test_api_errors_surface_code_and_message():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            json={
                "detail": {
                    "code": "operation_limit_reached",
                    "message": "monthly operation limit reached",
                }
            },
        )

    with pytest.raises(SuperDocsAPIError) as excinfo:
        await _client(handler).start_edit("s1", "cap liability")
    assert excinfo.value.status_code == 429
    assert excinfo.value.code == "operation_limit_reached"
    assert "monthly operation limit" in excinfo.value.message


async def test_non_json_error_body_still_produces_a_useful_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="<html>Bad Gateway</html>")

    with pytest.raises(SuperDocsAPIError) as excinfo:
        await _client(handler).start_edit("s1", "cap liability")
    assert excinfo.value.status_code == 502
    assert "Bad Gateway" in excinfo.value.message


async def test_invalid_open_mode_is_caught_before_any_network_call():
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must not reach the network with an invalid open_mode")

    with pytest.raises(ValueError) as excinfo:
        await _client(handler).upload_document(
            "MSA.docx", b"x", session_id="s1", open_mode="sideways"
        )
    assert "background" in str(excinfo.value)


async def test_a_binary_export_body_is_returned_as_bytes_not_decoded():
    """Regression: the export endpoint streams a .docx, and .json() choked on it.

    The failure surfaced as "'utf-8' codec can't decode byte 0xc8 in position 10" --
    an error from inside a ZIP header that says nothing about what went wrong.
    """
    docx_bytes = b"PK\x03\x04\x14\x00\x06\x00\x08\x00\xc8\xde\xad\xbe\xef"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=docx_bytes,
            headers={
                "content-type": (
                    "application/vnd.openxmlformats-officedocument."
                    "wordprocessingml.document"
                ),
                "content-disposition": 'attachment; filename="Acme_MSA.docx"',
            },
        )

    result = await _client(handler).export_document("s1", fmt="docx")
    assert result.content_bytes() == docx_bytes
    assert result.filename == "Acme_MSA.docx", "the server's own filename should win"


async def test_a_json_export_body_still_works():
    """The documented JSON shape must keep working; this is an addition, not a swap."""
    import base64

    payload = base64.b64encode(b"docx-bytes").decode()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"filename": "MSA.docx", "format": "docx", "content_b64": payload},
            headers={"content-type": "application/json"},
        )

    result = await _client(handler).export_document("s1", fmt="docx")
    assert result.content_bytes() == b"docx-bytes"
    assert result.filename == "MSA.docx"


async def test_an_error_on_a_binary_endpoint_still_reports_properly():
    """A failed export must raise a SuperDocsAPIError, not a decode error."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404,
            json={"detail": {"code": "session_not_found", "message": "no such session"}},
        )

    with pytest.raises(SuperDocsAPIError) as excinfo:
        await _client(handler).export_document("s1", fmt="docx")
    assert excinfo.value.code == "session_not_found"


async def test_a_markdown_export_returns_bytes_not_just_text():
    """Regression: text-format exports came back with no bytes to hand anyone.

    `export` documents docx, pdf, html, markdown and txt. Treating the text formats as
    "text" rather than "a file" meant `content_bytes()` raised for three of the five.
    """
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"# Master Services Agreement\n\nSection 8...",
            headers={
                "content-type": "text/markdown; charset=utf-8",
                "content-disposition": 'attachment; filename="MSA.md"',
            },
        )

    result = await _client(handler).export_document("s1", fmt="md")
    assert result.content_bytes().startswith(b"# Master Services Agreement")
    assert result.filename == "MSA.md"


async def test_export_warnings_are_surfaced_not_swallowed():
    """A non-fatal problem the server told us about must not vanish into a success."""
    import base64 as b64

    warnings = [{"code": "unsupported_style", "message": "a table style was simplified"}]
    header = b64.b64encode(json.dumps(warnings).encode()).decode()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"PK\x03\x04binary",
            headers={
                "content-type": (
                    "application/vnd.openxmlformats-officedocument."
                    "wordprocessingml.document"
                ),
                "x-export-warnings": header,
            },
        )

    result = await _client(handler).export_document("s1", fmt="docx")
    assert result.warnings == warnings


async def test_a_malformed_warnings_header_does_not_break_a_good_export():
    """The warning must never be able to break the thing it is warning about."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"PK\x03\x04binary",
            headers={
                "content-type": "application/pdf",
                "x-export-warnings": "!!!not-base64!!!",
            },
        )

    result = await _client(handler).export_document("s1", fmt="pdf")
    assert result.content_bytes() == b"PK\x03\x04binary"
    assert result.warnings is None
