"""
Callback abstraction for long-running SuperDocs jobs.

IMPORTANT, and stated here as the single source of truth for this distinction:
SuperDocs itself has NO push-webhook / callback-registration mechanism (verified
against docs.superdocs.app — job status is only observable by polling
GET /v1/jobs/{job_id} or opening an SSE stream, both pull-based). Nothing in
this connector should be read as SuperDocs calling us back. The connector's own
job worker (worker.py) polls SuperDocs on the recipe's behalf, and only once
that polling reaches a terminal state does *this* layer originate a callback —
to the enterprise integration platform, not from SuperDocs.

CallbackDispatcher is the seam that makes that platform-side callback pluggable:
Workato, Tray, Boomi, and MuleSoft each have their own inbound-webhook /
resume-recipe mechanism. WebhookCallbackDispatcher (a plain HTTP POST to a
recipe-supplied URL) covers all four in practice — every one of them can
receive an inbound webhook to resume a paused recipe — so the platform-specific
subclasses below are thin: they exist to document each platform's expected
payload/header conventions at the point a real integration would need to
verify them, not because the POST mechanism itself differs.
"""
from __future__ import annotations

import asyncio
import logging
import random
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx

from connector.config import ConnectorConfig
from schemas.poll import PollOutput

logger = logging.getLogger("superdocs_connector.callbacks")


@dataclass
class JobCallbackEvent:
    """What gets delivered to the platform once a SuperDocs job reaches a
    terminal state (completed / failed / awaiting_approval / cancelled)."""
    job_id: str
    status: str
    poll_result: PollOutput
    occurred_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    operation_id: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "occurred_at": self.occurred_at,
            "operation_id": self.operation_id,
            "result": self.poll_result.model_dump(mode="json"),
        }


class CallbackDispatcher(ABC):
    """Implement this to wire job-completion notification into a specific
    enterprise platform's resume-recipe mechanism."""

    @abstractmethod
    async def dispatch(self, event: JobCallbackEvent) -> None:
        ...


class LoggingCallbackDispatcher(CallbackDispatcher):
    """No-op dispatcher that just logs. Used in tests and as a safe default
    so a misconfigured recipe fails loud in logs rather than silently."""

    def __init__(self):
        self.received: list[JobCallbackEvent] = []

    async def dispatch(self, event: JobCallbackEvent) -> None:
        self.received.append(event)
        logger.info("Callback dispatched (logging only): job_id=%s status=%s", event.job_id, event.status)


class CallbackDeliveryError(Exception):
    """
    Raised when a callback could not be delivered after all bounded retries.
    Deliberately NOT a SuperDocsConnectorError subclass: this is a failure of
    the connector's own callback layer, never the SuperDocs job itself, and
    must never be confused with (or allowed to overwrite) that job's real
    completed/failed outcome, which was already determined before dispatch
    was ever attempted (see worker.py — poll_until_terminal resolves the job
    status first; dispatch() is only called after, with that status fixed).
    """
    def __init__(self, message: str, *, attempts: int, last_status_code: int | None = None):
        super().__init__(message)
        self.attempts = attempts
        self.last_status_code = last_status_code


class WebhookCallbackDispatcher(CallbackDispatcher):
    """
    Generic HTTP POST to a recipe-supplied callback URL, with bounded retry
    (exponential backoff + jitter, configurable via ConnectorConfig) for
    transient delivery failures — a callback endpoint being briefly
    unreachable is common in real integration platforms (a Workato/Tray/
    Boomi/MuleSoft webhook trigger can be temporarily unavailable during a
    deploy) and should not be treated as fatal on the first attempt. This is
    the mechanism underlying every platform-specific subclass below —
    Workato, Tray, Boomi, and MuleSoft all expose an inbound webhook trigger
    a recipe can pause on and resume from, so 'POST a JSON payload to a URL
    the platform gave us' is the actual integration point in all four cases.
    """

    def __init__(self, callback_url: str, *, extra_headers: dict[str, str] | None = None,
                 timeout_seconds: float = 30.0, config: ConnectorConfig | None = None):
        self.callback_url = callback_url
        self.extra_headers = extra_headers or {}
        self.timeout_seconds = timeout_seconds
        self._config = config
        self.attempts_made = 0  # last dispatch's attempt count, exposed for tests/observability

    def _retry_params(self) -> tuple[int, float, float, float]:
        if self._config is not None:
            return (self._config.callback_max_attempts, self._config.callback_initial_interval_seconds,
                    self._config.callback_max_interval_seconds, self._config.callback_backoff_factor)
        from connector.config import (
            DEFAULT_CALLBACK_BACKOFF_FACTOR,
            DEFAULT_CALLBACK_INITIAL_INTERVAL_SECONDS,
            DEFAULT_CALLBACK_MAX_ATTEMPTS,
            DEFAULT_CALLBACK_MAX_INTERVAL_SECONDS,
        )
        return (DEFAULT_CALLBACK_MAX_ATTEMPTS, DEFAULT_CALLBACK_INITIAL_INTERVAL_SECONDS,
                DEFAULT_CALLBACK_MAX_INTERVAL_SECONDS, DEFAULT_CALLBACK_BACKOFF_FACTOR)

    async def dispatch(self, event: JobCallbackEvent) -> None:
        max_attempts, initial, maximum, factor = self._retry_params()
        headers = {"Content-Type": "application/json", **self.extra_headers}
        payload = event.to_payload()

        last_status: int | None = None
        last_exc: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            self.attempts_made = attempt
            try:
                async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                    response = await client.post(self.callback_url, json=payload, headers=headers)
                if 200 <= response.status_code < 300:
                    logger.info("Callback POSTed to %s for job_id=%s status=%s (attempt %d)",
                                self.callback_url, event.job_id, event.status, attempt)
                    return
                last_status = response.status_code
                # 4xx (excluding 429) from the platform's own webhook endpoint
                # is almost certainly a misconfiguration (bad URL, revoked
                # trigger) that a retry won't fix -- fail fast rather than
                # burn the whole retry budget on a guaranteed-repeat 404.
                if 400 <= response.status_code < 500 and response.status_code != 429:
                    raise CallbackDeliveryError(
                        f"Callback endpoint rejected delivery with {response.status_code} "
                        f"(non-retryable client error) after {attempt} attempt(s)",
                        attempts=attempt, last_status_code=response.status_code,
                    )
            except httpx.HTTPError as exc:
                last_exc = exc

            if attempt < max_attempts:
                delay = min(initial * (factor ** (attempt - 1)), maximum)
                delay = delay * (1 + random.uniform(-0.2, 0.2))
                logger.warning("Callback delivery attempt %d/%d failed (status=%s); retrying in %.1fs",
                                attempt, max_attempts, last_status, delay)
                await asyncio.sleep(max(0.05, delay))

        raise CallbackDeliveryError(
            f"Callback delivery to {self.callback_url} failed after {max_attempts} attempts "
            f"(last_status={last_status}, last_error={last_exc})",
            attempts=max_attempts, last_status_code=last_status,
        )


class WorkatoCallbackDispatcher(WebhookCallbackDispatcher):
    """
    Adaptation point for Workato: Workato recipes resume from a paused state
    via its own webhook trigger step (a recipe configured with a Webhook
    trigger exposes a stable inbound URL). Pass that URL as `callback_url`.
    Workato does not require a special header for a plain webhook trigger, but
    if the target recipe's trigger is configured with a shared secret /
    signature check, pass it via `extra_headers`. Documented, not certified —
    verify against a real Workato recipe before production use.
    """
    pass


class TrayCallbackDispatcher(WebhookCallbackDispatcher):
    """
    Adaptation point for Tray.io: a Tray workflow resumes from a paused
    Wait-for-Webhook step via the URL that step generates. Pass it as
    `callback_url`. Tray's generated webhook URLs are unguessable by design
    and require no extra header; if the workflow uses HMAC verification, set
    it via `extra_headers`. Documented, not certified.
    """
    pass


class BoomiCallbackDispatcher(WebhookCallbackDispatcher):
    """
    Adaptation point for Boomi: an AtomSphere process resumes via a Listener
    (HTTP Client connector configured as a Listener), which exposes its own
    inbound endpoint URL. Boomi listeners commonly expect Basic Auth or an
    API-key header rather than a bare POST — supply it via `extra_headers`
    (e.g. `{"Authorization": "Basic ..."}`). Documented, not certified.
    """
    pass


class MuleSoftCallbackDispatcher(WebhookCallbackDispatcher):
    """
    Adaptation point for MuleSoft: an Anypoint flow resumes via an HTTP
    Listener component's endpoint, typically fronted by API Manager with a
    client-id/client-secret or bearer-token policy — supply the required
    headers via `extra_headers`. Documented, not certified.
    """
    pass
