"""SuperDocsClient: real tests, no live key required — uses httpx.MockTransport
instead of the network. Covers the behaviors that matter: happy path, permanent
errors are never retried, transient errors are retried with backoff, and the
idempotency store prevents a duplicate network call on a caller-level retry.
"""

from __future__ import annotations

import httpx

from core.idempotency import IdempotencyStore
from core.superdocs_client import (
    SuperDocsClient,
    SuperDocsPermanentError,
)


def _client(handler: httpx.MockTransport, **kwargs: object) -> SuperDocsClient:
    return SuperDocsClient(
        api_key="sk_test",
        http_client=httpx.Client(base_url="https://fake", transport=handler),
        **kwargs,  # type: ignore[arg-type]
    )


def test_happy_path() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat"
        return httpx.Response(200, json={"response": "ok", "session_id": "s1"})

    client = _client(httpx.MockTransport(handler))
    result = client.chat("hello", "s1")
    assert result == {"response": "ok", "session_id": "s1"}


def test_4xx_is_permanent_and_not_retried() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(422, json={"detail": "validation error"})

    client = _client(httpx.MockTransport(handler))
    try:
        client.chat("hello", "s1")
        raise AssertionError("expected SuperDocsPermanentError")
    except SuperDocsPermanentError:
        pass
    assert calls["n"] == 1, "4xx must not be retried"


def test_5xx_is_transient_and_retried_until_success() -> None:
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] < 3:
            return httpx.Response(503, json={"error": "temporarily unavailable"})
        return httpx.Response(200, json={"response": "recovered"})

    client = _client(httpx.MockTransport(handler))
    result = client.chat("hello", "s1")
    assert result == {"response": "recovered"}
    assert attempts["n"] == 3


def test_approve_is_idempotent_on_caller_retry(
    idempotency_store: IdempotencyStore,
) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json={"job_id": "job-1", "status": "approved"})

    client = _client(httpx.MockTransport(handler), idempotency_store=idempotency_store)

    r1 = client.approve(
        session_id="test-s1", job_id="test-job-1", approved=True, change_id="ch_1"
    )
    r2 = client.approve(
        session_id="test-s1", job_id="test-job-1", approved=True, change_id="ch_1"
    )

    assert calls["n"] == 1, "a repeated approve() call must not re-hit the network"
    assert r1 == r2


def test_approve_always_sends_top_level_approved() -> None:
    """The llms-full.txt gotcha: `approved` must be present at the top level even
    for batch shapes, or SuperDocs returns a generic 422. Assert our client always
    includes it."""
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured.update(json.loads(request.content))
        return httpx.Response(200, json={})

    client = _client(httpx.MockTransport(handler))
    client.approve(
        session_id="s1",
        job_id="job-1",
        approved=True,
        changes=[{"change_id": "ch_1", "approved": True}, {"change_id": "ch_2"}],
    )
    assert captured["approved"] is True, "top-level `approved` must always be sent"
    assert "changes" in captured


def test_chat_async_returns_job_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/async"
        return httpx.Response(200, json={"job_id": "job-async-1", "status": "pending"})

    client = _client(httpx.MockTransport(handler))
    result = client.chat_async("Draft a memo", "s1", approval_mode="ask_every_time")
    assert result["job_id"] == "job-async-1"


def test_chat_async_sends_approval_mode_and_document_html() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"job_id": "job-1"})

    client = _client(httpx.MockTransport(handler))
    client.chat_async(
        "Draft a memo",
        "s1",
        document_html="<p>verbatim content</p>",
        approval_mode="ask_every_time",
    )
    assert captured["approval_mode"] == "ask_every_time"
    assert captured["document_html"] == "<p>verbatim content</p>"


def test_chat_async_is_idempotent_on_caller_retry_without_starting_a_second_job(
    idempotency_store: IdempotencyStore,
) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json={"job_id": f"job-{calls['n']}"})

    client = _client(httpx.MockTransport(handler), idempotency_store=idempotency_store)
    r1 = client.chat_async("draft", "s1", request_id="fixed-key-1")
    r2 = client.chat_async("draft", "s1", request_id="fixed-key-1")

    assert calls["n"] == 1, "a repeated chat_async call with the same request_id must not start a second job"
    assert r1 == r2


def test_get_job_is_never_cached_and_always_hits_the_network(
    idempotency_store: IdempotencyStore,
) -> None:
    """The whole point of polling is reading CURRENT status -- an idempotency
    cache here would mean every poll after the first returns a stale
    snapshot forever, which would make the awaiting_approval -> completed
    transition invisible to the caller."""
    statuses = iter(["pending", "in_progress", "awaiting_approval", "completed"])

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/jobs/job-1"
        assert request.method == "GET"
        return httpx.Response(200, json={"status": next(statuses)})

    client = _client(httpx.MockTransport(handler), idempotency_store=idempotency_store)
    seen = [client.get_job("job-1")["status"] for _ in range(4)]
    assert seen == ["pending", "in_progress", "awaiting_approval", "completed"]


def test_get_job_surfaces_pending_changes_while_awaiting_approval() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status": "awaiting_approval",
                "metadata": {
                    "pending_changes": [
                        {"change_id": "ch_1", "chunk_id": "c1", "new_html": "<p>x</p>"}
                    ]
                },
            },
        )

    client = _client(httpx.MockTransport(handler))
    job = client.get_job("job-1")
    assert job["status"] == "awaiting_approval"
    assert job["metadata"]["pending_changes"][0]["change_id"] == "ch_1"


def test_cancel_job_is_idempotent_on_caller_retry(
    idempotency_store: IdempotencyStore,
) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        assert request.url.path == "/v1/jobs/job-1/cancel"
        return httpx.Response(200, json={"status": "cancelled"})

    client = _client(httpx.MockTransport(handler), idempotency_store=idempotency_store)
    r1 = client.cancel_job("job-1")
    r2 = client.cancel_job("job-1")

    assert calls["n"] == 1, "a repeated cancel_job call must not re-hit the network"
    assert r1 == r2


def test_export_html_returns_raw_text_content_not_json() -> None:
    """The real bug this closes (2026-08-11, caught via a real account
    call, not a mock): /v1/documents/export's real response is the raw
    exported file, never a JSON envelope. Confirmed against the live API:
    Content-Type: text/html for format=html. The old implementation called
    resp.json() unconditionally and would have raised a JSON-decode error
    on every real export call."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/documents/export"
        return httpx.Response(
            200,
            headers={
                "content-type": "text/html; charset=utf-8",
                "content-disposition": 'attachment; filename="Memo.html"; filename*=UTF-8\'\'Memo.html',
            },
            content=b"<h1>Exported Memo</h1><p>hello</p>",
        )

    client = _client(httpx.MockTransport(handler))
    result = client.export(html="<h1>Exported Memo</h1><p>hello</p>", format="html")

    assert result["content"] == "<h1>Exported Memo</h1><p>hello</p>"
    assert isinstance(result["content"], str)
    assert result["content_type"].startswith("text/html")
    assert result["filename"] == "Memo.html"
    assert result["format"] == "html"


def test_export_docx_returns_raw_bytes_content() -> None:
    """Same real finding, binary-format side: Content-Type is the real
    docx MIME type, and the body is raw zip/Open-XML bytes, never JSON."""
    fake_docx_bytes = b"PK\x03\x04fake-docx-zip-bytes-not-real-office-xml"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={
                "content-type": (
                    "application/vnd.openxmlformats-officedocument"
                    ".wordprocessingml.document"
                ),
                "content-disposition": 'attachment; filename="Memo.docx"; filename*=UTF-8\'\'Memo.docx',
            },
            content=fake_docx_bytes,
        )

    client = _client(httpx.MockTransport(handler))
    result = client.export(html="<h1>Memo</h1>", format="docx")

    assert result["content"] == fake_docx_bytes
    assert isinstance(result["content"], bytes)
    assert "wordprocessingml" in result["content_type"]
    assert result["filename"] == "Memo.docx"


def test_export_requires_session_id_or_html() -> None:
    client = _client(httpx.MockTransport(lambda r: httpx.Response(200)))
    try:
        client.export(format="html")
        raise AssertionError("expected SuperDocsPermanentError")
    except SuperDocsPermanentError:
        pass


def test_export_4xx_is_permanent_and_not_retried() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(422, json={"detail": "bad format"})

    client = _client(httpx.MockTransport(handler))
    try:
        client.export(html="<h1>x</h1>", format="html")
        raise AssertionError("expected SuperDocsPermanentError")
    except SuperDocsPermanentError:
        pass
    assert calls["n"] == 1
