import base64
import json

import httpx
import pytest

from connector.errors import UnsupportedFormatError
from connector.operations.upload_document import upload_document
from schemas.upload import INLINE_UPLOAD_SAFE_BYTES, UploadInput
from tests.conftest import json_response


@pytest.mark.asyncio
async def test_small_file_uses_inline_base64_strategy(fake_server, client):
    def handler(request):
        body = json.loads(request.content)
        assert body["filename"] == "contract.docx"
        assert base64.b64decode(body["file_base64"]) == b"small content"
        assert "session_id" in body
        return json_response(200, {
            "session_id": body["session_id"], "chunks_count": 3, "version_id": "v1",
        })

    fake_server.on("POST", "/v1/documents/upload-base64", handler)

    result = await upload_document(client, UploadInput(filename="contract.docx", content=b"small content"))

    assert result.strategy_used == "inline_base64"
    assert result.chunks_count == 3
    assert result.version_id == "v1"
    assert result.upload_id is None


@pytest.mark.asyncio
async def test_large_file_uses_presigned_url_strategy(fake_server, client):
    big_content = b"x" * (INLINE_UPLOAD_SAFE_BYTES + 1)

    def request_url_handler(request):
        body = json.loads(request.content)
        assert body["size_bytes"] == len(big_content)
        assert body["purpose"] == "document"
        return json_response(200, {
            "upload_id": "up_123", "upload_url": "https://storage.example.com/put/abc",
            "expires_at": "2026-01-01T00:00:00Z", "expires_in_seconds": 300,
            "max_size_bytes": 104857600, "curl_example": "curl ...",
        })

    put_calls = {"n": 0, "body": None}

    def storage_put_handler(request):
        put_calls["n"] += 1
        put_calls["body"] = request.content
        assert "authorization" not in {k.lower() for k in request.headers.keys()}, \
            "SuperDocs API key must never be sent to the pre-signed storage URL"
        return httpx.Response(200)

    def process_handler(request):
        body = json.loads(request.content)
        assert body["session_id"]
        assert body["filename"] == "big.pdf"
        return json_response(200, {
            "session_id": body["session_id"], "filename": "big.pdf",
            "status": "completed", "parse_mode": "document",
            "chunks_count": 40, "version_id": "v2",
        })

    fake_server.on("POST", "/v1/uploads", request_url_handler)
    fake_server.on("PUT", "/put/abc", storage_put_handler)
    fake_server.on("POST", "/v1/uploads/up_123/process", process_handler)

    result = await upload_document(client, UploadInput(filename="big.pdf", content=big_content))

    assert result.strategy_used == "presigned_url"
    assert result.upload_id == "up_123"
    assert result.chunks_count == 40
    assert put_calls["n"] == 1
    assert put_calls["body"] == big_content


@pytest.mark.asyncio
async def test_force_presigned_routes_small_file_through_presigned_path(fake_server, client):
    fake_server.on("POST", "/v1/uploads", lambda r: json_response(200, {
        "upload_id": "up_999", "upload_url": "https://storage.example.com/put/z",
        "expires_at": "x", "expires_in_seconds": 300, "max_size_bytes": 104857600, "curl_example": "x",
    }))
    fake_server.on("PUT", "/put/z", lambda r: httpx.Response(200))
    fake_server.on("POST", "/v1/uploads/up_999/process", lambda r: json_response(200, {
        "session_id": "s1", "filename": "tiny.txt", "status": "completed", "parse_mode": "document",
    }))

    result = await upload_document(client, UploadInput(filename="tiny.txt", content=b"hi", force_presigned=True))
    assert result.strategy_used == "presigned_url"


@pytest.mark.asyncio
async def test_unsupported_legacy_doc_extension_is_rejected_client_side(fake_server, client):
    with pytest.raises(UnsupportedFormatError, match=r"\.doc"):
        await upload_document(client, UploadInput(filename="old.doc", content=b"legacy content"))
    # Rejected before any HTTP call was made.
    assert fake_server.requests == []


@pytest.mark.asyncio
async def test_upload_response_parsing_preserves_all_typed_fields(fake_server, client):
    fake_server.on("POST", "/v1/documents/upload-base64", lambda r: json_response(200, {
        "session_id": "s-explicit", "chunks_count": 7, "version_id": "v9", "html": "<p>hi</p>",
    }))

    result = await upload_document(client, UploadInput(
        filename="doc.txt", content=b"hello", session_id="s-explicit",
    ))

    assert result.session_id == "s-explicit"
    assert result.chunks_count == 7
    assert result.version_id == "v9"
    assert result.html == "<p>hi</p>"


def test_upload_input_rejects_filename_without_extension():
    with pytest.raises(Exception, match="extension"):
        UploadInput(filename="noextension", content=b"data")


def test_upload_input_rejects_content_over_presigned_max():
    from schemas.upload import PRESIGNED_UPLOAD_MAX_BYTES
    with pytest.raises(Exception, match="100MB|byte"):
        UploadInput(filename="huge.pdf", content=b"x" * (PRESIGNED_UPLOAD_MAX_BYTES + 1))
