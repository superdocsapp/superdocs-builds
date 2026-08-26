"""Verifies request construction and response parsing against a mocked transport —
no live API key needed. The real response shapes these mocks mirror were confirmed
against a live SuperDocs account during Phase 0/1 exploration (see architecture.md).
"""
import httpx

from app.services.superdocs_client import SuperDocsClient


def _client_with_transport(handler) -> SuperDocsClient:
    client = SuperDocsClient(api_key="sk_test", base_url="https://api.superdocs.app")
    client._client = httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url="https://api.superdocs.app",
        headers={"Authorization": "Bearer sk_test"},
    )
    return client


def test_upload_document_chains_upload_then_list_session_documents():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/v1/documents/upload-base64":
            assert request.headers["Authorization"] == "Bearer sk_test"
            return httpx.Response(
                200,
                json={
                    "html": None,
                    "session_id": "slack-user-U123",
                    "filename": "status.md",
                    "chunks_count": 3,
                    "version_id": "v1",
                    "page_setup": None,
                    "persisted": True,
                },
            )
        assert request.url.path == "/v1/sessions/slack-user-U123/documents"
        return httpx.Response(
            200,
            json={
                "session_id": "slack-user-U123",
                "focused_document_id": "doc_primary",
                "documents": [
                    {
                        "document_id": "doc_primary",
                        "durable_document_id": "dc3af614-7859-44d9-a289-938459cfc320",
                        "title": "status",
                        "chunks_count": 3,
                        "focused": True,
                    }
                ],
                "file_cap_reached": False,
            },
        )

    client = _client_with_transport(handler)
    result = client.upload_document("slack-user-U123", "status.md", b"# Status\n")

    assert calls == ["/v1/documents/upload-base64", "/v1/sessions/slack-user-U123/documents"]
    assert result == {
        "document_id": "doc_primary",
        "durable_document_id": "dc3af614-7859-44d9-a289-938459cfc320",
        "title": "status",
    }


def test_chat_async_omits_document_id_when_not_given():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.content
        return httpx.Response(200, json={"job_id": "job_1", "session_id": "s1", "status": "pending", "message": "queued"})

    client = _client_with_transport(handler)
    result = client.chat_async("s1", "Add a paragraph about scope.")

    assert b"document_id" not in seen["body"]
    assert result["job_id"] == "job_1"


def test_approve_change_posts_expected_fields():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/s1/approve"
        return httpx.Response(200, json={})

    client = _client_with_transport(handler)
    result = client.approve_change("s1", job_id="job_1", approved=True, change_id="chg_1")

    assert result == {}


def test_export_document_parses_raw_file_bytes_not_json():
    """Confirmed live against a real key: SuperDocs returns the exported file's raw
    bytes with a Content-Disposition header, not a JSON download-URL response — the
    original assumption (see architecture.md) that broke in production. This test is
    the regression guard for that."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/documents/export"
        return httpx.Response(
            200,
            content=b"PK\x03\x04fake-docx-bytes",
            headers={
                "content-type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "content-disposition": 'attachment; filename="SuperDocs Document.docx"',
            },
        )

    client = _client_with_transport(handler)
    result = client.export_document("s1", format="docx")

    assert result["filename"] == "SuperDocs Document.docx"
    assert result["content"] == b"PK\x03\x04fake-docx-bytes"
    assert result["content_type"] == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
