import asyncio

import httpx
import pytest

from connector.callbacks import (
    CallbackDeliveryError,
    JobCallbackEvent,
    LoggingCallbackDispatcher,
    WebhookCallbackDispatcher,
)
from connector.http_client import SuperDocsHTTPClient
from connector.worker import JobWorker
from schemas.common import JobStatus
from schemas.poll import PollOutput
from tests.conftest import json_response


def _poll_output(status: JobStatus, **kwargs) -> PollOutput:
    return PollOutput(job_id="j1", status=status, **kwargs)


@pytest.mark.asyncio
async def test_callback_after_completed():
    dispatcher = LoggingCallbackDispatcher()
    event = JobCallbackEvent(job_id="j1", status="completed", poll_result=_poll_output(JobStatus.completed))
    await dispatcher.dispatch(event)

    assert len(dispatcher.received) == 1
    assert dispatcher.received[0].status == "completed"


@pytest.mark.asyncio
async def test_callback_after_failed():
    dispatcher = LoggingCallbackDispatcher()
    event = JobCallbackEvent(job_id="j1", status="failed", poll_result=_poll_output(JobStatus.failed, error="Model timeout"))
    await dispatcher.dispatch(event)

    assert dispatcher.received[0].poll_result.error == "Model timeout"


@pytest.mark.asyncio
async def test_approval_required_callback_carries_pending_changes():
    from schemas.common import AwaitingKind, ChangeOperation, PendingChange
    dispatcher = LoggingCallbackDispatcher()
    poll_result = _poll_output(
        JobStatus.awaiting_approval, awaiting_kind=AwaitingKind.change_review,
        pending_changes=[PendingChange(change_id="c1", operation=ChangeOperation.edit, chunk_id="ch1")],
    )
    event = JobCallbackEvent(job_id="j1", status="awaiting_approval", poll_result=poll_result)
    await dispatcher.dispatch(event)

    payload = event.to_payload()
    assert payload["result"]["pending_changes"][0]["change_id"] == "c1"


@pytest.mark.asyncio
async def test_webhook_dispatcher_posts_expected_payload(mock_callback_transport):
    received = {}

    def handler(request: httpx.Request) -> httpx.Response:
        received["body"] = request.content
        return httpx.Response(200)

    mock_callback_transport(httpx.MockTransport(handler))

    dispatcher = WebhookCallbackDispatcher("https://platform.example.com/webhook/abc")
    event = JobCallbackEvent(job_id="j1", status="completed", poll_result=_poll_output(JobStatus.completed), operation_id="op1")
    await dispatcher.dispatch(event)

    import json
    sent = json.loads(received["body"])
    assert sent["job_id"] == "j1"
    assert sent["operation_id"] == "op1"


@pytest.mark.asyncio
async def test_callback_retries_on_transient_failure_then_succeeds(fast_config, mock_callback_transport):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503)
        return httpx.Response(200)

    mock_callback_transport(httpx.MockTransport(handler))

    dispatcher = WebhookCallbackDispatcher("https://platform.example.com/hook", config=fast_config)
    event = JobCallbackEvent(job_id="j1", status="completed", poll_result=_poll_output(JobStatus.completed))
    await dispatcher.dispatch(event)

    assert calls["n"] == 3
    assert dispatcher.attempts_made == 3


@pytest.mark.asyncio
async def test_callback_exhausts_retries_and_raises_delivery_error(fast_config, mock_callback_transport):
    mock_callback_transport(httpx.MockTransport(lambda r: httpx.Response(503)))

    dispatcher = WebhookCallbackDispatcher("https://platform.example.com/hook", config=fast_config)
    event = JobCallbackEvent(job_id="j1", status="completed", poll_result=_poll_output(JobStatus.completed))
    with pytest.raises(CallbackDeliveryError) as exc_info:
        await dispatcher.dispatch(event)

    assert exc_info.value.attempts == fast_config.callback_max_attempts


@pytest.mark.asyncio
async def test_callback_4xx_fails_fast_without_burning_all_retries(fast_config, mock_callback_transport):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(404)  # misconfigured URL -- retrying won't help

    mock_callback_transport(httpx.MockTransport(handler))

    dispatcher = WebhookCallbackDispatcher("https://platform.example.com/hook", config=fast_config)
    event = JobCallbackEvent(job_id="j1", status="completed", poll_result=_poll_output(JobStatus.completed))
    with pytest.raises(CallbackDeliveryError):
        await dispatcher.dispatch(event)

    assert calls["n"] == 1, "a 404 from the callback endpoint should not be retried"


@pytest.mark.asyncio
async def test_callback_delivery_failure_does_not_corrupt_superdocs_job_state(fake_server, fast_config):
    """
    The critical isolation guarantee: the SuperDocs job's own outcome (here,
    genuinely 'completed', per the fake SuperDocs server) is fully resolved
    BEFORE callback dispatch is attempted. If callback delivery then fails
    completely, start_background must swallow that failure (log it) rather
    than raise -- and must never retroactively report the job as anything
    other than what SuperDocs actually said it was.
    """
    fake_server.on("GET", "/v1/jobs/j1", lambda r: json_response(200, {
        "job_id": "j1", "status": "completed", "result": {"response": "ok"},
    }))
    client = SuperDocsHTTPClient(fast_config, transport=httpx.MockTransport(fake_server))
    worker = JobWorker(fast_config, client)

    class AlwaysFailsDispatcher:
        async def dispatch(self, event):
            raise CallbackDeliveryError("simulated total delivery failure", attempts=3)

    task = worker.start_background("j1", AlwaysFailsDispatcher())
    await asyncio.wait_for(task, timeout=5)  # must not raise -- failure is caught and logged
    assert task.exception() is None

    # The SuperDocs job's real state is still queryable independently of the
    # (failed) callback -- nothing was corrupted.
    from connector.operations.poll_for_completion import poll_for_completion
    from schemas.poll import PollInput
    result = await poll_for_completion(client, PollInput(job_id="j1"))
    assert result.status == JobStatus.completed
