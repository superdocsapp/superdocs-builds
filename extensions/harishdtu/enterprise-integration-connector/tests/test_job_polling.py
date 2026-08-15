
import pytest

from connector.errors import NotFoundError
from connector.errors import TimeoutError as SDTimeoutError
from connector.operations.poll_for_completion import poll_for_completion
from connector.worker import _next_poll_delay, poll_until_terminal
from schemas.common import AwaitingKind, JobStatus
from schemas.poll import PollInput
from tests.conftest import json_response


@pytest.mark.asyncio
async def test_status_pending(fake_server, client):
    fake_server.on("GET", "/v1/jobs/j1", lambda r: json_response(200, {"job_id": "j1", "status": "pending"}))
    result = await poll_for_completion(client, PollInput(job_id="j1"))
    assert result.status == JobStatus.pending


@pytest.mark.asyncio
async def test_status_in_progress(fake_server, client):
    fake_server.on("GET", "/v1/jobs/j1", lambda r: json_response(200, {"job_id": "j1", "status": "in_progress"}))
    result = await poll_for_completion(client, PollInput(job_id="j1"))
    assert result.status == JobStatus.in_progress


@pytest.mark.asyncio
async def test_status_awaiting_approval_change_review_branch(fake_server, client):
    fake_server.on("GET", "/v1/jobs/j1", lambda r: json_response(200, {
        "job_id": "j1", "status": "awaiting_approval",
        "metadata": {"pending_changes": [
            {"change_id": "c1", "operation": "edit", "chunk_id": "ch1",
             "old_html": "<p>old</p>", "new_html": "<p>new</p>", "ai_explanation": "clarity"},
        ]},
    }))
    result = await poll_for_completion(client, PollInput(job_id="j1"))
    assert result.status == JobStatus.awaiting_approval
    assert result.awaiting_kind == AwaitingKind.change_review
    assert len(result.pending_changes) == 1
    assert result.pending_changes[0].change_id == "c1"
    assert result.continue_prompt is None


@pytest.mark.asyncio
async def test_status_awaiting_approval_continue_prompt_branch(fake_server, client):
    """The critical distinction (brief section 8): awaiting_kind=='continue_prompt'
    must route differently from a normal change review."""
    fake_server.on("GET", "/v1/jobs/j1", lambda r: json_response(200, {
        "job_id": "j1", "status": "awaiting_approval",
        "metadata": {"awaiting_kind": "continue_prompt",
                     "continue_prompt": {"message": "Continue rewriting section 4?", "done": 4, "total": 10, "remaining": 6}},
    }))
    result = await poll_for_completion(client, PollInput(job_id="j1"))
    assert result.status == JobStatus.awaiting_approval
    assert result.awaiting_kind == AwaitingKind.continue_prompt
    assert result.continue_prompt.remaining == 6
    assert result.pending_changes == []


@pytest.mark.asyncio
async def test_status_completed_with_result(fake_server, client):
    fake_server.on("GET", "/v1/jobs/j1", lambda r: json_response(200, {
        "job_id": "j1", "status": "completed",
        "result": {"response": "Done", "document_changes": {"updated_html": "<p>final</p>", "version_id": "v3"}},
    }))
    result = await poll_for_completion(client, PollInput(job_id="j1"))
    assert result.status == JobStatus.completed
    assert result.result.updated_html == "<p>final</p>"


@pytest.mark.asyncio
async def test_status_failed_with_error(fake_server, client):
    fake_server.on("GET", "/v1/jobs/j1", lambda r: json_response(200, {
        "job_id": "j1", "status": "failed", "error": "Model provider unavailable",
    }))
    result = await poll_for_completion(client, PollInput(job_id="j1"))
    assert result.status == JobStatus.failed
    assert result.error == "Model provider unavailable"


@pytest.mark.asyncio
async def test_status_cancelled(fake_server, client):
    fake_server.on("GET", "/v1/jobs/j1", lambda r: json_response(200, {"job_id": "j1", "status": "cancelled"}))
    result = await poll_for_completion(client, PollInput(job_id="j1"))
    assert result.status == JobStatus.cancelled


@pytest.mark.asyncio
async def test_expired_job_returns_404_as_typed_not_found(fake_server, client):
    fake_server.on("GET", "/v1/jobs/j_old", lambda r: json_response(404, {"detail": "Job not found"}))
    with pytest.raises(NotFoundError):
        await poll_for_completion(client, PollInput(job_id="j_old"))


def test_poll_backoff_grows_and_caps():
    d0 = _next_poll_delay(0, initial=2.0, maximum=30.0, factor=1.5, jitter_ratio=0.0)
    d1 = _next_poll_delay(1, initial=2.0, maximum=30.0, factor=1.5, jitter_ratio=0.0)
    d2 = _next_poll_delay(2, initial=2.0, maximum=30.0, factor=1.5, jitter_ratio=0.0)
    d_far = _next_poll_delay(20, initial=2.0, maximum=30.0, factor=1.5, jitter_ratio=0.0)
    assert d0 == pytest.approx(2.0)
    assert d1 == pytest.approx(3.0)
    assert d2 == pytest.approx(4.5)
    assert d_far == pytest.approx(30.0)  # capped at maximum, never exceeds it


def test_poll_backoff_jitter_stays_within_ratio():
    for _ in range(50):
        d = _next_poll_delay(3, initial=10.0, maximum=100.0, factor=1.0, jitter_ratio=0.2)
        assert 8.0 <= d <= 12.0  # base=10, +/-20%


@pytest.mark.asyncio
async def test_poll_until_terminal_stops_on_completed(fake_server, client, fast_config):
    import httpx

    from connector.http_client import SuperDocsHTTPClient
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] < 3:
            return json_response(200, {"job_id": "j1", "status": "in_progress"})
        return json_response(200, {"job_id": "j1", "status": "completed", "result": {"response": "ok"}})

    fake_server.on("GET", "/v1/jobs/j1", handler)
    fast_client = SuperDocsHTTPClient(fast_config, transport=httpx.MockTransport(fake_server))

    result = await poll_until_terminal(
        fast_client, "j1",
        poll_initial_interval_seconds=fast_config.poll_initial_interval_seconds,
        poll_max_interval_seconds=fast_config.poll_max_interval_seconds,
        poll_backoff_factor=fast_config.poll_backoff_factor,
        poll_jitter_ratio=fast_config.poll_jitter_ratio,
        max_poll_seconds=fast_config.max_poll_seconds,
    )
    assert result.status == JobStatus.completed
    assert calls["n"] == 3


@pytest.mark.asyncio
async def test_poll_until_terminal_times_out_without_reaching_terminal_state(fake_server, client, fast_config):
    import httpx

    from connector.http_client import SuperDocsHTTPClient

    fake_server.on("GET", "/v1/jobs/j1", lambda r: json_response(200, {"job_id": "j1", "status": "in_progress"}))
    fast_client = SuperDocsHTTPClient(fast_config, transport=httpx.MockTransport(fake_server))

    with pytest.raises(SDTimeoutError, match="did not reach a terminal state"):
        await poll_until_terminal(
            fast_client, "j1",
            poll_initial_interval_seconds=fast_config.poll_initial_interval_seconds,
            poll_max_interval_seconds=fast_config.poll_max_interval_seconds,
            poll_backoff_factor=fast_config.poll_backoff_factor,
            poll_jitter_ratio=fast_config.poll_jitter_ratio,
            max_poll_seconds=0.05,  # force timeout almost immediately
        )
