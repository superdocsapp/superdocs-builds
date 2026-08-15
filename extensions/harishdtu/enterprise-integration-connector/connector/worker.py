"""
The job worker: polls GET /v1/jobs/{job_id} until a terminal state, then hands
off to a CallbackDispatcher. `start_background` is the piece that satisfies
"the recipe worker must NOT block while waiting for a long-running SuperDocs
job" — it returns an asyncio.Task immediately; the actual polling loop runs
concurrently, off the caller's return path.

Terminal states, per docs.superdocs.app/guides/async-jobs: completed, failed,
cancelled, and awaiting_approval (a pause, not a failure — the platform still
needs to be notified so its recipe can branch into an approval step).
"""
from __future__ import annotations

import asyncio
import logging
import random
import time

from connector.callbacks import CallbackDispatcher, JobCallbackEvent
from connector.config import ConnectorConfig
from connector.errors import NotFoundError
from connector.errors import TimeoutError as SDTimeoutError
from connector.http_client import SuperDocsHTTPClient
from schemas.common import AwaitingKind, JobStatus
from schemas.poll import ContinuePrompt, JobResult, PendingChange, PollOutput

logger = logging.getLogger("superdocs_connector.worker")

_TERMINAL_STATUSES = frozenset({
    JobStatus.completed, JobStatus.failed, JobStatus.cancelled, JobStatus.awaiting_approval,
})


def _parse_poll_response(job_id: str, payload: dict) -> PollOutput:
    status = JobStatus(payload["status"])
    metadata = payload.get("metadata") or {}

    awaiting_kind = None
    continue_prompt = None
    pending_changes: list[PendingChange] = []
    if status == JobStatus.awaiting_approval:
        raw_kind = metadata.get("awaiting_kind")
        if raw_kind == "continue_prompt":
            awaiting_kind = AwaitingKind.continue_prompt
            cp = metadata.get("continue_prompt") or {}
            continue_prompt = ContinuePrompt(**cp) if cp else None
        else:
            awaiting_kind = AwaitingKind.change_review
            pending_changes = [PendingChange(**c) for c in metadata.get("pending_changes", [])]

    result = None
    if status == JobStatus.completed and "result" in payload:
        r = payload["result"]
        dc = r.get("document_changes") or {}
        result = JobResult(
            response=r.get("response"),
            updated_html=dc.get("updated_html"),
            version_id=dc.get("version_id"),
            changes_summary=dc.get("changes_summary"),
            usage=r.get("usage"),
        )

    return PollOutput(
        job_id=job_id,
        status=status,
        awaiting_kind=awaiting_kind,
        result=result,
        error=payload.get("error"),
        pending_changes=pending_changes,
        continue_prompt=continue_prompt,
    )


async def poll_once(client: SuperDocsHTTPClient, job_id: str) -> PollOutput:
    """A single poll; raises NotFoundError if the job has aged out of
    SuperDocs' ~1 hour retention window (see config.py's DEFAULT_MAX_POLL_SECONDS)."""
    payload = await client.get_json(f"/v1/jobs/{job_id}")
    return _parse_poll_response(job_id, payload)


def _next_poll_delay(attempt: int, *, initial: float, maximum: float, factor: float, jitter_ratio: float) -> float:
    """
    Configurable backoff for the job-status polling loop: starts at `initial`,
    grows by `factor` each attempt, capped at `maximum`, with +/-jitter_ratio
    jitter so many concurrent recipe workers polling the same connector don't
    all hit SuperDocs in lockstep. attempt is 0-indexed (first call = 0).
    """
    base = min(initial * (factor ** attempt), maximum)
    jitter = base * jitter_ratio
    return max(0.1, base + random.uniform(-jitter, jitter))


async def poll_until_terminal(
    client: SuperDocsHTTPClient,
    job_id: str,
    *,
    poll_initial_interval_seconds: float,
    poll_max_interval_seconds: float,
    poll_backoff_factor: float,
    poll_jitter_ratio: float,
    max_poll_seconds: int,
) -> PollOutput:
    """
    Blocking (within this coroutine) poll loop — the caller decides whether to
    await this directly or wrap it in a background task via `start_background`
    below. Raises SDTimeoutError if max_poll_seconds elapses without reaching
    a terminal state, rather than polling indefinitely toward a job that
    SuperDocs will eventually purge anyway. Delay between polls grows via
    _next_poll_delay rather than a fixed interval, so a job that's still
    "pending" after 30 seconds isn't hammered every 2 seconds for the next
    54 minutes.
    """
    started = time.monotonic()
    attempt = 0
    while True:
        result = await poll_once(client, job_id)
        if result.status in _TERMINAL_STATUSES:
            return result

        elapsed = time.monotonic() - started
        if elapsed >= max_poll_seconds:
            raise SDTimeoutError(
                f"Job {job_id} did not reach a terminal state within {max_poll_seconds}s "
                f"(last status: {result.status.value}). SuperDocs jobs are purged ~1 hour "
                f"after creation; persist the job_id and result state on the platform side "
                f"if you need to resume tracking beyond this window.",
                status_code=None, detail=result.status.value,
            )
        delay = _next_poll_delay(
            attempt, initial=poll_initial_interval_seconds, maximum=poll_max_interval_seconds,
            factor=poll_backoff_factor, jitter_ratio=poll_jitter_ratio,
        )
        # Never poll past the deadline just because the last computed delay overshoots it.
        delay = min(delay, max(0.0, max_poll_seconds - elapsed))
        await asyncio.sleep(delay)
        attempt += 1


class JobWorker:
    """
    Wraps a SuperDocsHTTPClient with the poll-then-callback lifecycle. One
    worker instance is fine to reuse across many jobs — it holds no per-job
    state itself (each background task carries its own).
    """

    def __init__(self, config: ConnectorConfig, client: SuperDocsHTTPClient):
        self._config = config
        self._client = client

    async def run_to_terminal(self, job_id: str) -> PollOutput:
        return await poll_until_terminal(
            self._client, job_id,
            poll_initial_interval_seconds=self._config.poll_initial_interval_seconds,
            poll_max_interval_seconds=self._config.poll_max_interval_seconds,
            poll_backoff_factor=self._config.poll_backoff_factor,
            poll_jitter_ratio=self._config.poll_jitter_ratio,
            max_poll_seconds=self._config.max_poll_seconds,
        )

    def start_background(
        self,
        job_id: str,
        callback: CallbackDispatcher,
        *,
        operation_id: str | None = None,
    ) -> asyncio.Task:
        """
        Returns immediately with an asyncio.Task already scheduled — this is
        what makes the recipe non-blocking. The task itself polls to a
        terminal state and then dispatches the callback; failures in either
        step are caught and logged rather than raised into an unretrieved
        task exception (which asyncio would otherwise only surface as a
        garbage-collection warning, easy to miss in a long-running worker
        process).
        """
        async def _run():
            try:
                result = await self.run_to_terminal(job_id)
                event = JobCallbackEvent(
                    job_id=job_id, status=result.status.value,
                    poll_result=result, operation_id=operation_id,
                )
                await callback.dispatch(event)
            except NotFoundError:
                logger.warning("Job %s not found while polling (likely aged out of "
                                "SuperDocs' retention window before reaching terminal state).", job_id)
            except Exception:
                logger.exception("Background job worker failed for job_id=%s", job_id)

        return asyncio.create_task(_run())
