"""The client's behaviour against a live API's failure modes, without a live API.

Both cases here were observed against the real service on 12 August 2026 and are
written up in ../bug-reports/superdocs-capacity-bugs.html. They are tested with a
transport stub rather than a network call, so the suite still runs with no key.
"""

from __future__ import annotations

import httpx
import pytest

from afteraction.client import AtCapacity, SuperDocsClient, SuperDocsError

CAPACITY_BODY = {
    "detail": {
        "error_code": "instance_at_capacity",
        "message_user": "The server is briefly at capacity running other AI requests. "
        "Nothing was changed. Retry this request in about 15 seconds.",
        "retry_after_seconds": 15,
        "max_concurrent_graph_runs": 6,
    }
}

# The async path's own words: it claims a 120s timeout on a job that died in 0.45s.
ASYNC_CAPACITY_ERROR = (
    "Instance at graph capacity — the AI run did not start within 120s. "
    "No work was performed; re-submit this request."
)


def _client(handler, **kwargs) -> SuperDocsClient:
    client = SuperDocsClient("sk_test", sleep=lambda _: None, **kwargs)
    client._http = httpx.Client(
        base_url="https://api.superdocs.app",
        transport=httpx.MockTransport(handler),
        headers={"Authorization": "Bearer sk_test"},
    )
    return client


def test_a_503_becomes_a_retryable_capacity_error():
    def handler(request):
        return httpx.Response(503, json=CAPACITY_BODY, headers={"retry-after": "15"})

    with pytest.raises(AtCapacity) as caught:
        _client(handler).upload_document("s", "f.html", "<p>x</p>")
    assert caught.value.retry_after == 15


def test_chat_resubmits_when_the_instance_is_busy_and_then_succeeds():
    """Re-submitting is safe only because both refusals state no work was performed."""
    calls = {"async": 0}

    def handler(request):
        path = request.url.path
        if path == "/v1/chat/async":
            calls["async"] += 1
            if calls["async"] < 3:
                return httpx.Response(503, json=CAPACITY_BODY)
            return httpx.Response(200, json={"job_id": "job-1", "status": "pending"})
        if path == "/v1/jobs/job-1":
            return httpx.Response(200, json={"status": "completed", "result": {"response": "done"}})
        return httpx.Response(404)

    client = _client(handler)
    result = client.chat("s", "edit this")
    assert result["response"] == "done"
    assert calls["async"] == 3
    assert client.usage.retries == 2


def test_a_job_that_fails_at_capacity_is_retried_not_reported_as_broken():
    """The async failure names a 120s timeout that never happened; the honest part is
    'No work was performed', so the correct response is to submit again."""
    calls = {"async": 0}

    def handler(request):
        path = request.url.path
        if path == "/v1/chat/async":
            calls["async"] += 1
            return httpx.Response(200, json={"job_id": f"job-{calls['async']}", "status": "pending"})
        if path.startswith("/v1/jobs/job-1"):
            return httpx.Response(
                200, json={"status": "failed", "progress": 79, "error": ASYNC_CAPACITY_ERROR}
            )
        if path.startswith("/v1/jobs/job-2"):
            return httpx.Response(200, json={"status": "completed", "result": {"response": "ok"}})
        return httpx.Response(404)

    client = _client(handler)
    assert client.chat("s", "edit")["response"] == "ok"
    assert calls["async"] == 2


def test_a_real_failure_is_not_mistaken_for_capacity():
    def handler(request):
        if request.url.path == "/v1/chat/async":
            return httpx.Response(200, json={"job_id": "job-1", "status": "pending"})
        return httpx.Response(200, json={"status": "failed", "error": "document not found"})

    with pytest.raises(SuperDocsError, match="document not found"):
        _client(handler).chat("s", "edit")


def test_capacity_eventually_gives_up_and_says_no_edit_was_applied():
    def handler(request):
        return httpx.Response(503, json=CAPACITY_BODY)

    with pytest.raises(AtCapacity, match="No edit was applied"):
        _client(handler, max_retries=2).chat("s", "edit")


def test_pending_changes_are_read_by_polling_not_from_the_stream():
    """Polling returns objects. The SSE path nests the batch as a JSON string inside an
    already-JSON event, and missing that second parse is the documented reason
    integrators see empty diff cards."""
    posted: list[dict] = []
    state = {"approved": False}

    def handler(request):
        path = request.url.path
        if path == "/v1/chat/async":
            return httpx.Response(200, json={"job_id": "job-1", "status": "pending"})
        if path == "/v1/jobs/job-1":
            if state["approved"]:
                return httpx.Response(200, json={"status": "completed", "result": {"response": "ok"}})
            return httpx.Response(
                200,
                json={
                    "status": "awaiting_approval",
                    "metadata": {
                        "pending_changes": [
                            {
                                "change_id": "ch_1",
                                "operation": "edit",
                                "chunk_id": "c1",
                                "old_html": "<p>old</p>",
                                "new_html": "<p>new</p>",
                                "ai_explanation": "why",
                            },
                            {
                                "change_id": "ch_2",
                                "operation": "edit",
                                "chunk_id": "c2",
                                "old_html": "<p>a</p>",
                                "new_html": "<p>b</p>",
                                "ai_explanation": "why2",
                            },
                        ]
                    },
                },
            )
        if path == "/v1/chat/s/approve":
            posted.append(__import__("json").loads(request.content))
            state["approved"] = True
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(404)

    client = _client(handler)
    client.chat("s", "edit", approver=lambda c: (c.change_id != "ch_2", "no"))

    assert len(posted) == 1
    body = posted[0]
    # top-level `approved` is required even for batch shapes; omitting it is a 422
    assert body["approved"] is True
    assert body["changes"] == [
        {"change_id": "ch_1", "approved": True},
        {"change_id": "ch_2", "approved": False, "feedback": "no"},
    ]


def test_a_large_edit_pause_is_continued_not_approved():
    """`awaiting_approval` has two flavours; calling /approve on the wrong one is a 409."""
    seen = {"continue": 0, "poll": 0}

    def handler(request):
        path = request.url.path
        if path == "/v1/chat/async":
            return httpx.Response(200, json={"job_id": "job-1", "status": "pending"})
        if path == "/v1/chat/s/continue":
            seen["continue"] += 1
            return httpx.Response(200, json={"ok": True})
        if path == "/v1/chat/s/approve":
            raise AssertionError("must not approve a continue_prompt pause")
        if path == "/v1/jobs/job-1":
            seen["poll"] += 1
            if seen["continue"]:
                return httpx.Response(200, json={"status": "completed", "result": {}})
            return httpx.Response(
                200,
                json={"status": "awaiting_approval", "metadata": {"awaiting_kind": "continue_prompt"}},
            )
        return httpx.Response(404)

    _client(handler).chat("s", "edit")
    assert seen["continue"] == 1


def test_export_writes_bytes_and_costs_nothing(tmp_path):
    def handler(request):
        return httpx.Response(200, content=b"PK\x03\x04docx-bytes")

    out = _client(handler).export("s", tmp_path / "report.docx")
    assert out.read_bytes().startswith(b"PK")


def test_a_missing_key_is_refused_before_any_call():
    with pytest.raises(SuperDocsError, match="no API key"):
        SuperDocsClient("")
