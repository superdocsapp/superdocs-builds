"""Graceful degradation and actionable errors, proven without a network or a key.

`SuperDocsClient` takes an injectable `session` and `sleep`, so these drive the
REAL retry/backoff/error code against a fake transport — no mocking library, no
patching, no waiting. What's exercised is the client's own logic, not a mock's.
"""
from __future__ import annotations

import pytest
import requests

from supplier_quality_drafter.client import SuperDocsClient, SuperDocsError


class FakeResponse:
    def __init__(self, status_code: int, json_body=None, headers=None, content=b""):
        self.status_code = status_code
        self._json = json_body
        self.headers = headers or ({"content-type": "application/json"} if json_body is not None else {})
        self.content = content
        self.text = str(json_body) if json_body is not None else ""

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json


class FakeSession:
    """Replays a scripted list of responses/exceptions, recording every call."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []
        self.headers = {}

    def request(self, method, url, **kwargs):
        self.calls.append((method, url))
        item = self.script.pop(0) if self.script else FakeResponse(200, {})
        if isinstance(item, Exception):
            raise item
        return item


def _client(script, **kwargs):
    slept = []
    client = SuperDocsClient(
        api_key="sk_test",
        session=FakeSession(script),
        sleep=slept.append,
        backoff_base=1.0,
        **kwargs,
    )
    return client, slept


# --- graceful degradation -----------------------------------------------------

def test_retries_a_429_and_then_succeeds():
    client, slept = _client([FakeResponse(429), FakeResponse(200, {"ok": True})])
    assert client.get_job("job-1") == {"ok": True}
    assert len(client._session.calls) == 2
    assert len(slept) == 1  # backed off once rather than dying


def test_retries_5xx_then_succeeds():
    client, slept = _client([FakeResponse(503), FakeResponse(502), FakeResponse(200, {"ok": True})])
    assert client.get_job("job-1") == {"ok": True}
    assert len(client._session.calls) == 3


def test_retries_a_dropped_connection():
    """A network blip mid-run must degrade into a slower run, not a failed one."""
    client, _ = _client([requests.ConnectionError("connection reset"), FakeResponse(200, {"ok": True})])
    assert client.get_job("job-1") == {"ok": True}


def test_gives_up_after_max_retries_with_an_actionable_message():
    client, _ = _client([FakeResponse(503)] * 10, max_retries=2)
    with pytest.raises(SuperDocsError) as exc:
        client.get_job("job-1")
    assert client._session.calls.__len__() == 3  # 1 attempt + 2 retries
    assert "Fix:" in str(exc.value)


def test_honors_retry_after_header_instead_of_its_own_backoff():
    client, slept = _client([
        FakeResponse(429, headers={"Retry-After": "7"}),
        FakeResponse(200, {"ok": True}),
    ])
    client.get_job("job-1")
    assert slept == [7.0]  # the server's number, not our backoff curve


def test_does_not_retry_a_client_error():
    """Retrying a 400 just wastes time — and for billable calls, money."""
    client, slept = _client([FakeResponse(400, {"detail": "bad field"})])
    with pytest.raises(SuperDocsError):
        client.get_job("job-1")
    assert len(client._session.calls) == 1
    assert slept == []


# --- errors that name the cause AND the fix -----------------------------------

@pytest.mark.parametrize("status,expected_hint", [
    (401, "SUPERDOCS_API_KEY"),
    (413, "pre-signed"),
    (415, "DOCX"),
    (422, "approved"),
    (504, "async"),
])
def test_error_messages_name_a_concrete_fix(status, expected_hint):
    client, _ = _client([FakeResponse(status, {"detail": "x"})] * 10, max_retries=0)
    with pytest.raises(SuperDocsError) as exc:
        client.get_job("job-1")
    message = str(exc.value)
    assert "Fix:" in message
    assert expected_hint in message


def test_missing_api_key_error_says_where_to_get_one():
    import os

    saved = os.environ.pop("SUPERDOCS_API_KEY", None)
    try:
        with pytest.raises(SuperDocsError) as exc:
            SuperDocsClient(api_key=None)
        assert "use.superdocs.app" in str(exc.value)
    finally:
        if saved is not None:
            os.environ["SUPERDOCS_API_KEY"] = saved


def test_verify_key_returns_false_on_401_rather_than_raising():
    client, _ = _client([FakeResponse(401, {"detail": "bad key"})], max_retries=0)
    assert client.verify_key() is False


# --- usage reporting ----------------------------------------------------------

def test_usage_is_read_from_the_server_not_estimated():
    body = {
        "response": "done",
        "usage": {"monthly_used": 44, "monthly_limit": 500, "monthly_remaining": 456, "subscription_tier": "free"},
    }
    client, _ = _client([FakeResponse(200, body)])
    client.chat("hi", session_id="s1")
    assert client.usage.calls == 1
    assert client.usage.monthly_used == 44
    assert "456 remaining" in client.usage.summary()


def test_usage_summary_is_honest_when_server_sends_no_usage_block():
    client, _ = _client([FakeResponse(200, {"response": "done"})])
    client.chat("hi", session_id="s1")
    assert "no usage block" in client.usage.summary()


def test_usage_block_is_found_inside_a_job_result_too():
    job = {"status": "completed", "result": {"usage": {"monthly_used": 7, "monthly_limit": 100, "monthly_remaining": 93}}}
    client, _ = _client([FakeResponse(200, job)])
    client.poll_job("job-1")
    assert client.usage.monthly_used == 7
