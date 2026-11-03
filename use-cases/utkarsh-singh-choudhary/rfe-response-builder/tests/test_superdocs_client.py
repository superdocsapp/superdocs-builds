"""
Direct tests for SuperDocsClient's unified retry/backoff path
(`_request_with_retry`) and idempotency-key header forwarding. Previously
only `chat()` retried transient failures; these tests cover the same
behavior now applying uniformly to `chat_async`, `get_job`,
`approve_change`, and `export`.
"""
import requests_mock

from rfe_response_builder.superdocs_client import SuperDocsClient, SuperDocsError


def _client():
    return SuperDocsClient(api_key="sk_test_fake_key_not_real", retry_backoff_s=0)


def test_export_retries_transient_failure_and_recovers():
    client = _client()
    with requests_mock.Mocker() as m:
        m.post(
            "https://api.superdocs.app/v1/documents/export",
            [{"status_code": 503, "json": {"detail": "temporarily unavailable"}},
             {"status_code": 200, "content": b"FAKE_DOCX"}],
        )
        result = client.export(session_id="s1", fmt="docx")
        assert result == b"FAKE_DOCX"
        assert m.call_count == 2


def test_approve_change_retries_transient_failure_and_recovers():
    client = _client()
    with requests_mock.Mocker() as m:
        m.post(
            "https://api.superdocs.app/v1/chat/s1/approve",
            [{"status_code": 502, "json": {"detail": "bad gateway"}},
             {"status_code": 200, "json": {"ok": True}}],
        )
        result = client.approve_change(session_id="s1", chunk_id="c1", approved=True)
        assert result == {"ok": True}
        assert m.call_count == 2


def test_chat_async_retries_transient_failure_and_recovers():
    client = _client()
    with requests_mock.Mocker() as m:
        m.post(
            "https://api.superdocs.app/v1/chat/async",
            [{"status_code": 429, "json": {"detail": "rate limited"}},
             {"status_code": 200, "json": {"job_id": "job-1"}}],
        )
        job_id = client.chat_async(session_id="s1", message="draft it")
        assert job_id == "job-1"
        assert m.call_count == 2


def test_get_job_retries_transient_failure_and_recovers():
    client = _client()
    with requests_mock.Mocker() as m:
        m.get(
            "https://api.superdocs.app/v1/jobs/job-1",
            [{"status_code": 500, "json": {"detail": "internal error"}},
             {"status_code": 200, "json": {"status": "completed", "response": "done"}}],
        )
        job = client.get_job("job-1")
        assert job["status"] == "completed"
        assert m.call_count == 2


def test_non_retryable_4xx_raises_immediately_without_retry():
    client = _client()
    with requests_mock.Mocker() as m:
        m.post("https://api.superdocs.app/v1/documents/export", status_code=400, json={"detail": "bad request"})
        try:
            client.export(session_id="s1")
            assert False, "expected SuperDocsError"
        except SuperDocsError as e:
            assert e.status_code == 400
        assert m.call_count == 1  # no retry attempted for a non-retryable status


def test_persistent_failure_raises_after_exhausting_retries():
    client = _client()
    with requests_mock.Mocker() as m:
        m.post("https://api.superdocs.app/v1/documents/export", status_code=503, json={"detail": "down"})
        try:
            client.export(session_id="s1")
            assert False, "expected SuperDocsError"
        except SuperDocsError as e:
            assert e.status_code == 503
        # max_retries defaults to 2 -> 3 total attempts (1 initial + 2 retries)
        assert m.call_count == 3


def test_chat_forwards_idempotency_key_header():
    client = _client()
    with requests_mock.Mocker() as m:
        m.post(
            "https://api.superdocs.app/v1/chat",
            json={"response": "drafted", "document_changes": {}},
        )
        client.chat(session_id="s1", message="draft it", idempotency_key="req-1-abc")
        assert m.last_request.headers["Idempotency-Key"] == "req-1-abc"


def test_chat_without_idempotency_key_omits_header():
    client = _client()
    with requests_mock.Mocker() as m:
        m.post(
            "https://api.superdocs.app/v1/chat",
            json={"response": "drafted", "document_changes": {}},
        )
        client.chat(session_id="s1", message="draft it")
        assert "Idempotency-Key" not in m.last_request.headers
