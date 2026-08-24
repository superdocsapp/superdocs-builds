import base64
import json
import logging

import httpx
import pytest
from pydantic import SecretStr

from docrelay.integrations.superdocs.client import (
    SuperDocsHTTPClient,
    SuperDocsInvalidResponse,
    SuperDocsRequestError,
)


@pytest.fixture
def api_key() -> SecretStr:
    return SecretStr("super-secret-superdocs-key")


async def test_multipart_upload_and_explicit_target_contract(api_key: SecretStr) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/v1/documents/upload":
            body = request.content
            assert request.method == "POST"
            assert request.headers["Authorization"] == "Bearer super-secret-superdocs-key"
            assert request.headers["Content-Type"].startswith("multipart/form-data; boundary=")
            assert b'name="file"; filename="baseline.docx"' in body
            assert (
                b"application/vnd.openxmlformats-officedocument.wordprocessingml.document" in body
            )
            assert b'name="session_id"' in body and b"docrelay-run-1" in body
            assert b'name="open_mode"' in body and b"replace" in body
            assert b"synthetic baseline bytes" in body
            return httpx.Response(
                200,
                headers={"X-Request-ID": "req-upload-1"},
                json={
                    "html": '<p data-chunk-id="fresh-1">45 days</p>',
                    "session_id": "docrelay-run-1",
                    "filename": "baseline.docx",
                    "chunks_count": 1,
                    "version_id": "upload-version-1",
                    "document_id": "doc_primary",
                    "documents": [{"document_id": "doc_primary"}],
                    "page_setup": None,
                    "persisted": True,
                },
            )
        if request.url.path == "/v1/sessions/docrelay-run-1/documents":
            assert request.method == "GET"
            assert request.url.params["include_html"] == "false"
            return httpx.Response(
                200,
                json={
                    "documents": [
                        {
                            "document_id": "doc_primary",
                            "durable_document_id": "durable-1",
                            "title": "baseline.docx",
                            "focused": True,
                            "chunks_count": 1,
                            "version_id": "upload-version-1",
                        }
                    ]
                },
            )
        if request.url.path == "/v1/chat/async":
            payload = json.loads(request.content)
            assert payload == {
                "message": "Change 45 days to 30 days and nothing else.",
                "session_id": "docrelay-run-1",
                "document_id": "doc_primary",
                "approval_mode": "ask_every_time",
                "response_mode": "full",
            }
            return httpx.Response(
                200,
                json={
                    "job_id": "job-1",
                    "session_id": "docrelay-run-1",
                    "status": "pending",
                    "message": "queued",
                },
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = SuperDocsHTTPClient(http=http, api_key=api_key)
        uploaded = await client.upload_docx(
            docx_bytes=b"synthetic baseline bytes",
            filename="baseline.docx",
            session_id="docrelay-run-1",
        )
        roster = await client.list_session_documents("docrelay-run-1")
        job = await client.start_edit(
            target=roster[0].identity,
            instruction="Change 45 days to 30 days and nothing else.",
        )

    assert uploaded.identity.session_document_id == "doc_primary"
    assert uploaded.upload_version_id == "upload-version-1"
    assert uploaded.baseline_html_sha256 != "0" * 64
    assert roster[0].identity.durable_document_id == "durable-1"
    assert job.job_id == "job-1"
    assert [request.url.path for request in requests] == [
        "/v1/documents/upload",
        "/v1/sessions/docrelay-run-1/documents",
        "/v1/chat/async",
    ]


async def test_review_shapes_mixed_decisions_and_continue_are_exact(api_key: SecretStr) -> None:
    calls: list[tuple[str, str, dict[str, object] | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content) if request.content else None
        calls.append((request.method, request.url.path, payload))
        if request.url.path == "/v1/jobs/job-1":
            return httpx.Response(
                200,
                json={
                    "job_id": "job-1",
                    "session_id": "session-1",
                    "job_type": "chat",
                    "status": "awaiting_approval",
                    "progress": 50,
                    "metadata": {
                        "pending_changes": [
                            {
                                "change_id": "change-a",
                                "operation": "edit",
                                "chunk_id": "chunk-a",
                                "document_id": "doc_primary",
                                "old_html": "<p>A</p>",
                                "new_html": "<p>A approved</p>",
                                "ai_explanation": "First proposal",
                            },
                            {
                                "change_id": "change-b",
                                "operation": "edit",
                                "chunk_id": "chunk-b",
                                "document_id": "doc_primary",
                                "old_html": "<p>B</p>",
                                "new_html": "<p>B rejected</p>",
                                "ai_explanation": "Second proposal",
                            },
                        ]
                    },
                },
            )
        if request.url.path == "/v1/chat/session-1/approve":
            assert payload == {
                "job_id": "job-1",
                "approved": True,
                "changes": [
                    {"change_id": "change-a", "approved": True},
                    {
                        "change_id": "change-b",
                        "approved": False,
                        "feedback": "Keep the original B text.",
                    },
                ],
            }
            return httpx.Response(
                200,
                json={
                    "status": "ok",
                    "message": "Approval processed",
                    "batch_complete": True,
                },
            )
        if request.url.path == "/v1/chat/session-1/continue":
            assert payload == {"job_id": "job-1", "continue": True}
            return httpx.Response(200, json={"status": "ok"})
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    from docrelay.integrations.superdocs.contracts import ChangeReviewDecision

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = SuperDocsHTTPClient(http=http, api_key=api_key)
        snapshot = await client.get_job("job-1")
        receipt = await client.submit_decisions(
            session_id="session-1",
            job_id="job-1",
            decisions=(
                ChangeReviewDecision(change_id="change-a", approved=True),
                ChangeReviewDecision(
                    change_id="change-b",
                    approved=False,
                    feedback="Keep the original B text.",
                ),
            ),
        )
        await client.submit_continue(session_id="session-1", job_id="job-1", should_continue=True)

    assert snapshot.awaiting_kind is None
    assert tuple(change.change_id for change in snapshot.pending_changes) == (
        "change-a",
        "change-b",
    )
    assert receipt.batch_complete
    assert len(calls) == 3


async def test_focus_precedes_binary_export_and_warning_decode(api_key: SecretStr) -> None:
    paths: list[str] = []
    warnings = base64.b64encode(
        json.dumps([{"code": "size_cap_warning", "message": "bounded"}]).encode()
    ).decode()

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/v1/sessions/session-1/documents/doc_primary/focus":
            assert request.url.params["include_html"] == "false"
            return httpx.Response(
                200,
                json={
                    "document_id": "doc_primary",
                    "durable_document_id": "durable-1",
                    "focused": True,
                    "version_id": "final-version-1",
                },
            )
        if request.url.path == "/v1/documents/export":
            assert paths[-2].endswith("/doc_primary/focus")
            assert json.loads(request.content) == {
                "session_id": "session-1",
                "format": "docx",
                "options": {"filename": "reviewed.docx", "fidelity": "strict"},
            }
            return httpx.Response(
                200,
                content=b"PK\x03\x04reviewed-docx",
                headers={
                    "Content-Type": (
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                    ),
                    "Content-Disposition": 'attachment; filename="reviewed.docx"',
                    "X-Export-Warnings": warnings,
                },
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    from docrelay.integrations.superdocs.contracts import SessionDocumentIdentity

    target = SessionDocumentIdentity(
        session_id="session-1",
        session_document_id="doc_primary",
        durable_document_id="durable-1",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = SuperDocsHTTPClient(http=http, api_key=api_key)
        focused = await client.focus_document(target)
        exported = await client.export_docx(target=target, filename="reviewed.docx")

    assert focused.focused
    assert exported.docx_bytes == b"PK\x03\x04reviewed-docx"
    assert exported.warnings[0]["code"] == "size_cap_warning"
    assert paths == [
        "/v1/sessions/session-1/documents/doc_primary/focus",
        "/v1/documents/export",
    ]


async def test_unknown_or_malformed_job_payload_fails_closed(api_key: SecretStr) -> None:
    responses = iter(
        [
            httpx.Response(
                200,
                json={
                    "job_id": "job-1",
                    "session_id": "session-1",
                    "status": "mystery",
                },
            ),
            httpx.Response(
                200,
                json={
                    "job_id": "job-1",
                    "session_id": "session-1",
                    "status": "awaiting_approval",
                    "metadata": {"pending_changes": "not-a-list"},
                },
            ),
        ]
    )

    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: next(responses))) as http:
        client = SuperDocsHTTPClient(http=http, api_key=api_key)
        with pytest.raises(SuperDocsInvalidResponse):
            await client.get_job("job-1")
        with pytest.raises(SuperDocsInvalidResponse):
            await client.get_job("job-1")


async def test_timeout_is_unknown_and_logs_are_secret_safe(
    api_key: SecretStr, caplog: pytest.LogCaptureFixture
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("synthetic provider timeout", request=request)

    caplog.set_level(logging.INFO)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = SuperDocsHTTPClient(http=http, api_key=api_key)
        with pytest.raises(SuperDocsRequestError) as caught:
            await client.start_edit_raw(
                session_id="session-1",
                document_id="doc_primary",
                instruction="CONFIDENTIAL DOCUMENT CONTENT 45 days",
            )

    assert caught.value.outcome_unknown
    rendered = caplog.text
    assert "super-secret-superdocs-key" not in rendered
    assert "CONFIDENTIAL DOCUMENT CONTENT" not in rendered
    assert "Authorization" not in rendered
