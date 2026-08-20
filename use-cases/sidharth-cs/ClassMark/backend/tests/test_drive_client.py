"""Drive API client tests — MockTransport, no network."""

import asyncio

import httpx

from app.google.drive import GoogleDriveClient


def _client(handler) -> GoogleDriveClient:
    c = GoogleDriveClient()
    c._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return c


def test_download_file_uses_alt_media():
    seen = {}

    async def handler(request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, content=b"real-docx-bytes")

    async def run():
        async with _client(handler) as c:
            content = await c.download_file("tok123", "d1", "application/pdf")
        assert content == b"real-docx-bytes"

    asyncio.run(run())
    assert "files/d1" in seen["url"]
    assert "alt=media" in seen["url"]
    assert seen["auth"] == "Bearer tok123"


def test_download_file_exports_native_google_doc_to_html():
    """Native Google Docs return nothing via alt=media — export endpoint
    with text/html is the correct path."""
    seen = {}

    async def handler(request):
        seen["url"] = str(request.url)
        return httpx.Response(200, content=b"<h1>Exported essay</h1>")

    async def run():
        async with _client(handler) as c:
            content = await c.download_file(
                "tok123", "d1", "application/vnd.google-apps.document"
            )
        assert b"<h1>Exported essay</h1>" in content

    asyncio.run(run())
    assert "/files/d1/export" in seen["url"]
    assert "mimeType=text%2Fhtml" in seen["url"] or "mimeType=text/html" in seen["url"]


def test_upload_file_multipart_contains_metadata_and_content():
    seen = {}

    async def handler(request):
        seen["url"] = str(request.url)
        seen["content_type"] = request.headers.get("content-type", "")
        seen["body"] = request.content
        return httpx.Response(200, json={"id": "r1", "name": "reviewed.docx"})

    async def run():
        async with _client(handler) as c:
            resp = await c.upload_file(
                "tok123", "essay_reviewed.docx", b"PK-DOCX",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        assert resp["id"] == "r1"

    asyncio.run(run())
    assert "uploadType=multipart" in seen["url"]
    assert "multipart/related" in seen["content_type"]
    assert b"PK-DOCX" in seen["body"]
    assert b'"name":"essay_reviewed.docx"' in seen["body"]


def test_get_file_metadata_requests_limited_fields():
    seen = {}

    async def handler(request):
        seen["url"] = str(request.url)
        return httpx.Response(
            200, json={"id": "d1", "name": "essay.docx", "mimeType": "application/pdf"}
        )

    async def run():
        async with _client(handler) as c:
            meta = await c.get_file_metadata("tok123", "d1")
        assert meta["name"] == "essay.docx"

    asyncio.run(run())
    assert "fields=" in seen["url"]
