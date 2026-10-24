import json

import httpx
import pytest
import respx
from pydantic import SecretStr

from app.config import Settings
from app.superdocs import SuperDocsClient


def settings() -> Settings:
    return Settings(
        superdocs_api_key=SecretStr("sk_test"),
        webhook_secret=SecretStr("s" * 32),
        github_webhook_secret=SecretStr("g" * 32),
        management_token=SecretStr("m" * 32),
        job_poll_interval_seconds=0,
        job_timeout_seconds=2,
    )


@respx.mock
async def test_full_upload_edit_and_export_flow() -> None:
    base = "https://api.superdocs.app"
    respx.post(f"{base}/v1/documents/upload").mock(
        return_value=httpx.Response(200, json={"html": '<p data-chunk-id="1">event</p>'})
    )
    respx.post(f"{base}/v1/chat/async").mock(
        return_value=httpx.Response(200, json={"job_id": "job_1"})
    )
    poll = respx.get(f"{base}/v1/jobs/job_1").mock(
        side_effect=[
            httpx.Response(200, json={"status": "in_progress"}),
            httpx.Response(200, json={"status": "completed"}),
        ]
    )
    respx.post(f"{base}/v1/documents/export").mock(
        return_value=httpx.Response(
            200,
            content=b"docx-bytes",
            headers={
                "content-type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "content-disposition": 'attachment; filename="event.docx"',
            },
        )
    )

    client = SuperDocsClient(settings())
    try:
        result = await client.process_event("evt_1", {"type": "invoice.paid"})
    finally:
        await client.close()

    assert result.content == b"docx-bytes"
    assert poll.call_count == 2


@respx.mock
async def test_parses_review_wait_and_submits_per_change_decisions() -> None:
    base = "https://api.superdocs.app"
    respx.get(f"{base}/v1/jobs/job_review").mock(
        return_value=httpx.Response(
            200,
            json={
                "status": "awaiting_approval",
                "metadata": {
                    "pending_changes": [
                        {
                            "change_id": "chg_1",
                            "operation": "edit",
                            "chunk_id": "chunk_1",
                            "old_html": "<p>old</p>",
                            "new_html": "<p>new</p>",
                            "ai_explanation": "Updated the status",
                        }
                    ]
                },
            },
        )
    )
    approve = respx.post(f"{base}/v1/chat/session_review/approve").mock(
        return_value=httpx.Response(200, json={"status": "in_progress"})
    )
    client = SuperDocsClient(settings())
    try:
        snapshot = await client.get_job("job_review")
        await client.submit_decisions(
            session_id="session_review",
            job_id="job_review",
            decisions=[{"change_id": "chg_1", "approved": False, "feedback": "Keep it"}],
        )
    finally:
        await client.close()

    assert snapshot.awaiting_kind == "change_review"
    assert snapshot.pending_changes[0].chunk_id == "chunk_1"
    payload = json.loads(approve.calls[0].request.content)
    assert payload["approved"] is True
    assert payload["changes"][0]["approved"] is False


@respx.mock
async def test_parses_json_encoded_pending_changes() -> None:
    base = "https://api.superdocs.app"
    encoded = json.dumps(
        [
            {
                "change_id": "chg_encoded",
                "operation": "create",
                "chunk_id": "chunk_encoded",
                "old_html": None,
                "new_html": "<p>new</p>",
                "ai_explanation": "Added a section",
            }
        ]
    )
    respx.get(f"{base}/v1/jobs/job_encoded").mock(
        return_value=httpx.Response(
            200,
            json={
                "status": "awaiting_approval",
                "metadata": {"pending_changes": json.dumps(encoded)},
            },
        )
    )
    client = SuperDocsClient(settings())
    try:
        snapshot = await client.get_job("job_encoded")
    finally:
        await client.close()

    assert snapshot.awaiting_kind == "change_review"
    assert [change.change_id for change in snapshot.pending_changes] == ["chg_encoded"]


@respx.mock
async def test_pending_changes_fail_closed_on_malformed_or_duplicate_items() -> None:
    base = "https://api.superdocs.app"
    route = respx.get(f"{base}/v1/jobs/job_bad").mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "status": "awaiting_approval",
                    "metadata": {"pending_changes": [{"change_id": "chg_1"}]},
                },
            ),
            httpx.Response(
                200,
                json={
                    "status": "awaiting_approval",
                    "metadata": {
                        "pending_changes": [
                            {"change_id": "chg_1", "operation": "edit"},
                            {"change_id": "chg_1", "operation": "delete"},
                        ]
                    },
                },
            ),
        ]
    )
    client = SuperDocsClient(settings())
    try:
        with pytest.raises(Exception, match="valid operation"):
            await client.get_job("job_bad")
        with pytest.raises(Exception, match="duplicate change IDs"):
            await client.get_job("job_bad")
    finally:
        await client.close()

    assert route.call_count == 2


@respx.mock
async def test_export_rejects_oversize_stream_before_returning_artifact() -> None:
    base = "https://api.superdocs.app"
    respx.post(f"{base}/v1/documents/export").mock(
        return_value=httpx.Response(
            200,
            content=b"x" * 1025,
            headers={"content-length": "1025"},
        )
    )
    configured = settings().model_copy(update={"max_artifact_bytes": 1024})
    client = SuperDocsClient(configured)
    try:
        with pytest.raises(Exception, match="artifact limit"):
            await client.export(
                event_id="evt", session_id="session", job_id="job", export_format="docx"
            )
    finally:
        await client.close()


@respx.mock
async def test_edit_route_opens_configured_file_and_preserves_chunk_html() -> None:
    base = "https://api.superdocs.app"
    document_html = '<h1 data-chunk-id="heading-1">Project status</h1>'
    detail = respx.get(f"{base}/v1/documents/doc_status?include_html=true").mock(
        return_value=httpx.Response(200, json={"id": "doc_status", "html": document_html})
    )
    init = respx.post(f"{base}/v1/sessions/init").mock(
        return_value=httpx.Response(200, json={"documents": [{"id": "doc_status"}]})
    )
    chat = respx.post(f"{base}/v1/chat/async").mock(
        return_value=httpx.Response(200, json={"job_id": "job_edit"})
    )

    client = SuperDocsClient(settings())
    try:
        started = await client.start_event(
            "evt_edit",
            {"type": "project.changed"},
            approval_mode="ask_every_time",
            instruction="Update only supplied facts.",
            target_document_id="doc_status",
        )
    finally:
        await client.close()

    assert started.job_id == "job_edit"
    assert detail.called and init.called and chat.called
    init_payload = json.loads(init.calls[0].request.content)
    assert init_payload == {
        "session_id": "webhook-evt_edit",
        "document_ids": ["doc_status"],
    }
    chat_payload = json.loads(chat.calls[0].request.content)
    assert chat_payload["document_html"] == document_html
    assert b"/v1/documents/upload" not in [call.request.url.path.encode() for call in detail.calls]


async def test_edit_route_rejects_malformed_configured_document_id() -> None:
    client = SuperDocsClient(settings())
    try:
        with pytest.raises(Exception, match="document ID is malformed"):
            await client.start_event(
                "evt_edit",
                {},
                approval_mode="ask_every_time",
                target_document_id="https://internal.example/document",
            )
    finally:
        await client.close()
