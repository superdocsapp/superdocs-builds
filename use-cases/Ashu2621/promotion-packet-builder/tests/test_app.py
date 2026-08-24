import json
from collections.abc import AsyncIterator
from typing import Any

import app as subject
import httpx
import pytest


class FakeMcp:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.reviewed = False
        self.keep_pending_after_review = False
        self.session_id = "promotion_1234567890abcdef"

    async def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((name, arguments))
        if name == "chat_async":
            return {"job_id": "job-test", "status": "pending"}
        if name == "chat":
            return {
                "answer": "The review reports a 42 percent latency reduction.",
                "citations": [{"filename": "review.txt", "quote": "42 percent"}],
            }
        if name == "list_user_templates":
            return {"templates": [{"name": "packet.docx"}]}
        if name == "get_job":
            if self.reviewed and not self.keep_pending_after_review:
                return {
                    "job_id": "job-test",
                    "session_id": self.session_id,
                    "status": "completed",
                    "pending_changes": [],
                }
            return {
                "job_id": "job-test",
                "session_id": self.session_id,
                "status": "awaiting_approval",
                "pending_changes": [
                    {
                        "change_id": "a",
                        "ai_explanation": "Supported by review.txt",
                        "citations": [
                            {"filename": "review.txt", "quote": "42 percent"}
                        ],
                    },
                    {
                        "change_id": "b",
                        "ai_explanation": "Supported by review.txt",
                        "citations": [
                            {"filename": "review.txt", "quote": "Reduced latency"}
                        ],
                    },
                ],
            }
        if name == "request_upload_url":
            return {
                "upload_url": "https://upload.example/signed",
                "upload_id": "upload-large",
            }
        if name == "export_document":
            return {"download_url": "https://download.example/export.docx"}
        if name == "approve_change":
            self.reviewed = True
            return {"status": "accepted"}
        return {"status": "ok"}


def setup_client() -> tuple[httpx.AsyncClient, FakeMcp]:
    subject._SESSION_ARTIFACTS.clear()
    subject._GROUNDED_SESSIONS.clear()
    subject._SESSION_ACTIVE_JOBS.clear()
    subject._REVIEWED_JOBS.clear()
    subject._IDEMPOTENCY.clear()
    fake = FakeMcp()

    async def override() -> AsyncIterator[FakeMcp]:
        yield fake

    subject.app.dependency_overrides[subject.provider] = override
    transport = httpx.ASGITransport(app=subject.app)
    return httpx.AsyncClient(transport=transport, base_url="http://test"), fake


@pytest.fixture(autouse=True)
def signed_url_hosts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPERDOCS_SIGNED_URL_HOSTS", "upload.example,download.example")


@pytest.mark.asyncio
async def test_upload_document_attachments_and_optional_template() -> None:
    client, fake = setup_client()
    async with client:
        response = await client.post(
            "/api/upload",
            files=[
                (
                    "primary",
                    (
                        "packet.docx",
                        b"PK synthetic document",
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    ),
                ),
                (
                    "evidence",
                    ("review.txt", b"Reduced latency by 42 percent.", "text/plain"),
                ),
            ],
            data={"save_template": "true"},
            headers={"Idempotency-Key": "upload-intent-0001"},
        )
    assert response.status_code == 200, response.text
    assert [name for name, _ in fake.calls] == [
        "upload_document_base64",
        "upload_template_base64",
        "upload_attachment_base64",
    ]
    assert response.json()["session_id"].startswith("promotion_")


@pytest.mark.asyncio
async def test_edit_and_mixed_review_force_safe_provider_contract() -> None:
    client, fake = setup_client()
    session_id = "promotion_1234567890abcdef"
    subject._SESSION_ARTIFACTS[session_id] = ("review.txt",)
    subject._SESSION_ACTIVE_JOBS[session_id] = "job-test"
    async with client:
        edited = await client.post(
            "/api/edit",
            headers={"Idempotency-Key": "edit-intent-0000001"},
            json={
                "session_id": session_id,
                "instruction": "Improve clarity but preserve the measured evidence.",
                "model_tier": "pro",
            },
        )
        edit_arguments = fake.calls[-1][1]
        reviewed = await client.post(
            "/api/review",
            headers={"Idempotency-Key": "review-intent-00001"},
            json={
                "session_id": session_id,
                "job_id": "job-test",
                "changes": [
                    {"change_id": "a", "approved": True},
                    {"change_id": "b", "approved": False, "feedback": "Unsupported."},
                ],
            },
        )
    assert edited.status_code == 200
    assert edit_arguments["approval_mode"] == "ask_every_time"
    assert edit_arguments["cross_session_memory"] is False
    assert edit_arguments["cross_session_search"] is False

    assert reviewed.status_code == 200
    arguments = next(arguments for name, arguments in fake.calls if name == "approve_change")
    assert arguments["approved"] is True
    assert [item["approved"] for item in arguments["changes"]] == [True, False]


@pytest.mark.asyncio
async def test_rejection_requires_feedback_and_export_proxies_without_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, fake = setup_client()
    session_id = "promotion_1234567890abcdef"
    subject._SESSION_ARTIFACTS[session_id] = ("review.txt",)
    subject._SESSION_ACTIVE_JOBS[session_id] = "job-test"
    async with client:
        invalid = await client.post(
            "/api/review",
            headers={"Idempotency-Key": "review-invalid-0001"},
            json={
                "session_id": session_id,
                "job_id": "job-test",
                "changes": [
                    {"change_id": "a", "approved": True},
                    {"change_id": "b", "approved": False},
                ],
            },
        )
        assert invalid.status_code == 422

        reviewed = await client.post(
            "/api/review",
            headers={"Idempotency-Key": "review-valid-000001"},
            json={
                "session_id": session_id,
                "job_id": "job-test",
                "changes": [
                    {"change_id": "a", "approved": True},
                    {"change_id": "b", "approved": False, "feedback": "Unsupported."},
                ],
            },
        )
        assert reviewed.status_code == 200

        class FakeDownloadResponse:
            async def aiter_bytes(self, _: int) -> AsyncIterator[bytes]:
                yield b"PK provider "
                yield b"docx"

            async def aclose(self) -> None:
                return None

        class FakeDownloadClient:
            async def aclose(self) -> None:
                return None

        async def open_download(
            url: str,
        ) -> tuple[FakeDownloadClient, FakeDownloadResponse]:
            assert url == "https://download.example/export.docx"
            return FakeDownloadClient(), FakeDownloadResponse()

        monkeypatch.setattr(subject, "open_download", open_download)
        exported = await client.post(
            "/api/export",
            headers={"Idempotency-Key": "export-intent-00001"},
            json={"session_id": session_id, "format": "docx"},
        )
    assert exported.status_code == 200
    assert exported.content == b"PK provider docx"
    assert fake.calls[-1][0] == "export_document"


@pytest.mark.asyncio
async def test_search_templates_and_idempotent_replay() -> None:
    client, fake = setup_client()
    session_id = "promotion_1234567890abcdef"
    subject._SESSION_ARTIFACTS[session_id] = ("review.txt",)
    headers = {"Idempotency-Key": "search-intent-00001"}
    async with client:
        templates = await client.get("/api/templates")
        first = await client.post(
            "/api/search",
            headers=headers,
            json={"session_id": session_id, "query": "latency result"},
        )
        replay = await client.post(
            "/api/search",
            headers=headers,
            json={"session_id": session_id, "query": "latency result"},
        )
    assert templates.json()["templates"][0]["name"] == "packet.docx"
    assert first.json() == replay.json()
    assert [name for name, _ in fake.calls].count("chat") == 1
    assert fake.calls[-1][1]["cross_session_search"] is False


@pytest.mark.asyncio
async def test_approval_requires_every_change_and_a_resolvable_citation() -> None:
    client, _ = setup_client()
    session_id = "promotion_1234567890abcdef"
    subject._SESSION_ARTIFACTS[session_id] = ("different-source.txt",)
    subject._SESSION_ACTIVE_JOBS[session_id] = "job-test"
    async with client:
        partial = await client.post(
            "/api/review",
            headers={"Idempotency-Key": "review-partial-0001"},
            json={
                "session_id": session_id,
                "job_id": "job-test",
                "changes": [{"change_id": "a", "approved": True}],
            },
        )
        assert partial.status_code == 409

        ungrounded = await client.post(
            "/api/review",
            headers={"Idempotency-Key": "review-grounding-001"},
            json={
                "session_id": session_id,
                "job_id": "job-test",
                "changes": [
                    {"change_id": "a", "approved": True},
                    {"change_id": "b", "approved": False, "feedback": "No source."},
                ],
            },
        )
    assert ungrounded.status_code == 409
    assert "no resolvable source" in ungrounded.text


def test_nested_proposed_change_string_is_parsed_twice() -> None:
    job = {
        "metadata": {
            "intermediate_responses": [
                {
                    "content": json.dumps(
                        json.dumps(
                            {
                                "changes": [
                                    {
                                        "change_id": "nested",
                                        "ai_explanation": "Grounded in review.txt",
                                        "citations": [
                                            {
                                                "filename": "review.txt",
                                                "quote": "42 percent",
                                            }
                                        ],
                                    }
                                ]
                            }
                        )
                    )
                }
            ]
        }
    }
    normalized = subject.normalize_job(job, ("review.txt",))
    assert normalized["normalized_changes"][0]["change_id"] == "nested"
    assert normalized["all_changes_grounded"] is True


@pytest.mark.asyncio
async def test_large_document_uses_streaming_presigned_upload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, fake = setup_client()
    streamed: list[tuple[str, str]] = []

    async def stream(url: str, file: Any, content_type: str) -> None:
        assert await subject.file_size(file) > subject.INLINE_FILE_BYTES
        streamed.append((url, content_type))

    monkeypatch.setattr(subject, "stream_to_signed_url", stream)
    async with client:
        response = await client.post(
            "/api/upload",
            headers={"Idempotency-Key": "upload-large-intent1"},
            files=[
                ("primary", ("large.docx", b"x" * 110_000, "application/octet-stream")),
                ("evidence", ("review.txt", b"source evidence", "text/plain")),
            ],
            data={"save_template": "false"},
        )
    assert response.status_code == 200, response.text
    assert response.json()["large_file_path"] == "presigned"
    assert streamed == [("https://upload.example/signed", "application/octet-stream")]
    names = [name for name, _ in fake.calls]
    assert "request_upload_url" in names
    assert "process_uploaded_document" in names
    assert "upload_document_base64" not in names


@pytest.mark.asyncio
async def test_cross_session_job_is_rejected_before_approval() -> None:
    client, fake = setup_client()
    session_id = "promotion_1234567890abcdef"
    subject._SESSION_ARTIFACTS[session_id] = ("review.txt",)
    subject._SESSION_ACTIVE_JOBS[session_id] = "job-test"
    fake.session_id = "promotion_aaaaaaaaaaaaaaaa"
    async with client:
        response = await client.post(
            "/api/review",
            headers={"Idempotency-Key": "review-owner-check1"},
            json={
                "session_id": session_id,
                "job_id": "job-test",
                "changes": [
                    {"change_id": "a", "approved": True},
                    {"change_id": "b", "approved": False, "feedback": "Not supported."},
                ],
            },
        )
    assert response.status_code == 409
    assert not any(name == "approve_change" for name, _ in fake.calls)


@pytest.mark.asyncio
async def test_revised_round_blocks_export_until_it_is_reviewed() -> None:
    client, fake = setup_client()
    session_id = "promotion_1234567890abcdef"
    subject._SESSION_ARTIFACTS[session_id] = ("review.txt",)
    subject._SESSION_ACTIVE_JOBS[session_id] = "job-test"
    fake.keep_pending_after_review = True
    async with client:
        reviewed = await client.post(
            "/api/review",
            headers={"Idempotency-Key": "review-revision-0001"},
            json={
                "session_id": session_id,
                "job_id": "job-test",
                "changes": [
                    {"change_id": "a", "approved": True},
                    {"change_id": "b", "approved": False, "feedback": "Revise it."},
                ],
            },
        )
        exported = await client.post(
            "/api/export",
            headers={"Idempotency-Key": "export-revision-001"},
            json={"session_id": session_id, "format": "docx"},
        )
    assert reviewed.status_code == 200
    assert reviewed.json()["export_ready"] is False
    assert exported.status_code == 409


def test_signed_url_validation_rejects_credentials_and_unlisted_hosts() -> None:
    with pytest.raises(subject.HTTPException):
        subject.validate_signed_url("https://user:secret@download.example/export.docx")
    with pytest.raises(subject.HTTPException):
        subject.validate_signed_url("https://127.0.0.1/export.docx")
