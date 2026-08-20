"""Offline tests for RealSuperDocsClient. No live SuperDocs key is used --
a fake requests.Session stands in for the HTTP layer, verified against the
real API's documented request/response shapes (see
app/clients/real_superdocs_client.py's module docstring for the mapping
this client makes from the abstract upload/chat/approve/export contract
onto the real REST surface).
"""
from __future__ import annotations

import json

import pytest

from app.clients.real_superdocs_client import RealSuperDocsClient
from app.clients.superdocs_client import SuperDocsAPIError


class FakeResponse:
    def __init__(self, status_code: int, json_body=None, content: bytes = b"", text: str = ""):
        self.status_code = status_code
        self._json_body = json_body if json_body is not None else {}
        self.content = content
        self.text = text or json.dumps(self._json_body)

    def json(self):
        return self._json_body


class FakeSession:
    """Records calls and serves scripted responses keyed by (method, url substring)."""

    def __init__(self):
        self.calls = []
        self._scripts = []  # list of (method, url_substring, response) consumed in order per key

    def script(self, method: str, url_substring: str, response: FakeResponse):
        self._scripts.append((method, url_substring, response))

    def _match(self, method, url):
        for i, (m, sub, resp) in enumerate(self._scripts):
            if m == method and sub in url:
                del self._scripts[i]
                return resp
        raise AssertionError(f"no scripted response for {method} {url}")

    def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append(("POST", url, json))
        return self._match("POST", url)

    def get(self, url, headers=None, timeout=None):
        self.calls.append(("GET", url, None))
        return self._match("GET", url)


def make_client(session: FakeSession, **kwargs) -> RealSuperDocsClient:
    return RealSuperDocsClient(
        api_key="sk_test",
        session=session,
        poll_interval=0.001,
        poll_timeout=1.0,
        **kwargs,
    )


def test_upload_posts_base64_and_returns_session_id_as_document_id():
    session = FakeSession()
    session.script("POST", "/v1/documents/upload-base64", FakeResponse(200, {"chunks_count": 3}))
    client = make_client(session)

    doc_id = client.upload("contract.txt", b"hello world")

    assert doc_id.startswith("box-")
    method, url, body = session.calls[0]
    assert body["filename"] == "contract.txt"
    assert body["session_id"] == doc_id
    import base64

    assert base64.b64decode(body["file_base64"]) == b"hello world"


def test_chat_completes_without_approval_and_parses_embedded_json():
    """Classify-style prompts ask the AI not to edit the document, so the
    job should go straight to completed with no pending change -- the
    proposed_change comes from JSON embedded in the reply text (the
    documented 'second parse')."""
    session = FakeSession()
    session.script("POST", "/v1/chat/async", FakeResponse(200, {"job_id": "job-1"}))
    reply_text = 'Sure thing! {"doc_class": "contract", "confidence": 0.87} done.'
    session.script(
        "GET",
        "/v1/jobs/job-1",
        FakeResponse(200, {"status": "completed", "result": {"response": reply_text}}),
    )
    client = make_client(session)

    result = client.chat("box-abc", "Please classify this document.")

    assert result.session_id == "job-1"
    assert result.proposed_change == {"doc_class": "contract", "confidence": 0.87}
    # the outgoing prompt should carry the JSON-only instruction appended
    _, _, chat_body = session.calls[0]
    assert "classify" in chat_body["message"].lower()
    assert chat_body["approval_mode"] == "ask_every_time"


def test_chat_raises_on_failed_job():
    session = FakeSession()
    session.script("POST", "/v1/chat/async", FakeResponse(200, {"job_id": "job-2"}))
    session.script(
        "GET",
        "/v1/jobs/job-2",
        FakeResponse(200, {"status": "failed", "result": {"error": "boom"}}),
    )
    client = make_client(session)

    with pytest.raises(SuperDocsAPIError, match="boom"):
        client.chat("box-abc", "Please classify this document.")


def test_approve_is_honest_noop_when_nothing_pending():
    """Most stages never produce a pending document change (we explicitly
    ask the AI not to edit), so approve() should check real job state and
    do nothing rather than call the approve endpoint on a completed job."""
    session = FakeSession()
    session.script("GET", "/v1/jobs/job-3", FakeResponse(200, {"status": "completed"}))
    client = make_client(session)

    client.approve("box-abc", "job-3")

    # only the status-check GET happened; no POST to /approve
    assert all(call[0] != "POST" for call in session.calls)


def test_approve_calls_real_endpoint_when_awaiting_approval():
    session = FakeSession()
    session.script(
        "GET",
        "/v1/jobs/job-4",
        FakeResponse(
            200,
            {
                "status": "awaiting_approval",
                "metadata": {"pending_changes": [{"change_id": "chg-1"}]},
            },
        ),
    )
    session.script("POST", "/v1/chat/box-abc/approve", FakeResponse(200, {}))
    session.script("GET", "/v1/jobs/job-4", FakeResponse(200, {"status": "completed"}))
    client = make_client(session)

    client.approve("box-abc", "job-4")

    approve_calls = [c for c in session.calls if c[0] == "POST"]
    assert len(approve_calls) == 1
    _, url, body = approve_calls[0]
    assert url.endswith("/v1/chat/box-abc/approve")
    assert body["job_id"] == "job-4"
    assert body["changes"] == [{"change_id": "chg-1", "approved": True}]


def test_export_posts_session_id_and_returns_bytes():
    session = FakeSession()
    session.script("POST", "/v1/documents/export", FakeResponse(200, content=b"docx-bytes"))
    client = make_client(session)

    result = client.export("box-abc")

    assert result == b"docx-bytes"
    _, _, body = session.calls[0]
    assert body == {"session_id": "box-abc", "format": "docx"}


def test_operations_budget_stops_before_hitting_the_api():
    session = FakeSession()
    client = make_client(session, max_operations=0)

    with pytest.raises(SuperDocsAPIError, match="budget exhausted"):
        client.chat("box-abc", "Please classify this document.")

    assert session.calls == []  # never even made the HTTP call


def test_http_error_raises_superdocs_api_error_with_detail():
    session = FakeSession()
    session.script(
        "POST",
        "/v1/documents/upload-base64",
        FakeResponse(401, {"detail": "Invalid API key"}),
    )
    client = make_client(session)

    with pytest.raises(SuperDocsAPIError, match="Invalid API key"):
        client.upload("f.txt", b"x")


def test_from_env_returns_none_without_api_key(monkeypatch):
    monkeypatch.delenv("SUPERDOCS_API_KEY", raising=False)
    assert RealSuperDocsClient.from_env() is None


def test_from_env_builds_client_with_key(monkeypatch):
    monkeypatch.setenv("SUPERDOCS_API_KEY", "sk_live_test")
    client = RealSuperDocsClient.from_env()
    assert client is not None
    assert client._api_key == "sk_live_test"


def test_error_carries_real_http_status_code_for_retry_classification():
    """SuperDocsAPIError raised from a real HTTP failure must carry the
    actual status_code so app.workflow.retry.is_retryable can classify
    it correctly (e.g. retry a 429/503, don't retry a 401/404) instead
    of falling back to guessing from message text."""
    session = FakeSession()
    session.script(
        "POST",
        "/v1/documents/upload-base64",
        FakeResponse(429, {"detail": "rate limited, slow down"}),
    )
    client = make_client(session)

    with pytest.raises(SuperDocsAPIError) as exc_info:
        client.upload("f.txt", b"x")
    assert exc_info.value.status_code == 429


def test_network_level_failure_is_wrapped_as_retryable_superdocs_error():
    """A connection-level failure (no HTTP response at all) must still
    surface as a SuperDocsAPIError so call_with_retry can see it and
    retry it, instead of a raw requests exception escaping the retry
    layer entirely."""
    import requests

    class DyingSession:
        def post(self, url, headers=None, json=None, timeout=None):
            raise requests.exceptions.ConnectionError("connection refused")

        def get(self, url, headers=None, timeout=None):
            raise requests.exceptions.ConnectionError("connection refused")

    client = make_client(DyingSession())

    with pytest.raises(SuperDocsAPIError) as exc_info:
        client.upload("f.txt", b"x")
    assert exc_info.value.status_code is None
    from app.workflow.retry import is_retryable

    assert is_retryable(exc_info.value) is True
