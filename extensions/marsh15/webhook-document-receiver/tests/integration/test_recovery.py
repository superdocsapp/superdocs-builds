import asyncio
import hashlib
import os
from typing import Literal

import psycopg
import pytest
from psycopg_pool import ConnectionPool

from app.config import get_settings
from app.persistence import DeliveryStore, LeaseLostError
from app.security import VerifiedWebhook
from app.superdocs import StartedJob
from app.worker import run_once

DATABASE_URL = os.getenv("TEST_DATABASE_URL")


class MustNotStartProcessor:
    async def start_event(
        self,
        event_id: str,
        payload: dict[str, object],
        *,
        approval_mode: Literal["approve_all", "ask_every_time"],
        instruction: str | None = None,
        model_tier: str | None = None,
        thinking_depth: str | None = None,
        target_document_id: str | None = None,
    ) -> StartedJob:
        raise AssertionError("An ambiguous expired lease must not repeat the external effect")


@pytest.mark.skipif(DATABASE_URL is None, reason="TEST_DATABASE_URL is not configured")
def test_expired_lease_after_possible_external_effect_needs_attention(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL or "")
    monkeypatch.setenv("SUPERDOCS_API_KEY", "test")
    monkeypatch.setenv("WEBHOOK_SECRET", "s" * 32)
    monkeypatch.setenv("MANAGEMENT_TOKEN", "m" * 32)
    get_settings.cache_clear()
    with ConnectionPool(DATABASE_URL or "", min_size=1, max_size=2) as pool:
        store = DeliveryStore(pool)
        accepted = store.accept(
            verified=VerifiedWebhook(
                provider="generic-hmac",
                event_id="evt_recovery",
                timestamp=1_700_000_000,
                payload_sha256=hashlib.sha256(b"recovery").hexdigest(),
            ),
            event_type="incident.resolved",
            route_id="incident-report",
            route_config_version="test-v1",
            input_data={"type": "incident.resolved"},
        )
        abandoned = store.claim(worker_id="dead-worker", lease_seconds=60)
        assert abandoned is not None
        store.mark_starting(job=abandoned)
        with psycopg.connect(DATABASE_URL) as connection:
            connection.execute(
                "UPDATE jobs SET lease_until = now() - interval '1 second' WHERE id = %s",
                (accepted.job_id,),
            )

        worked = asyncio.run(
            run_once(
                store=store,
                processor=MustNotStartProcessor(),  # type: ignore[arg-type]
                settings=get_settings(),
                worker_id="replacement-worker",
            )
        )
        assert worked is True
        assert store.status(accepted.delivery_id)["status"] == "needs_attention"  # type: ignore[index]

    get_settings.cache_clear()


@pytest.mark.skipif(DATABASE_URL is None, reason="TEST_DATABASE_URL is not configured")
def test_retry_wait_becomes_claimable_and_increments_retry_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL or "")
    monkeypatch.setenv("SUPERDOCS_API_KEY", "test")
    monkeypatch.setenv("WEBHOOK_SECRET", "s" * 32)
    monkeypatch.setenv("MANAGEMENT_TOKEN", "m" * 32)
    get_settings.cache_clear()
    with ConnectionPool(DATABASE_URL or "", min_size=1, max_size=2) as pool:
        store = DeliveryStore(pool)
        store.accept(
            verified=VerifiedWebhook(
                provider="generic-hmac",
                event_id="evt_retry",
                timestamp=1_700_000_000,
                payload_sha256=hashlib.sha256(b"retry").hexdigest(),
            ),
            event_type="incident.resolved",
            route_id="incident-report",
            route_config_version="test-v1",
            input_data={"type": "incident.resolved"},
        )
        first = store.claim(worker_id="worker-1", lease_seconds=60)
        assert first is not None
        store.retry(job=first, error=RuntimeError("temporary"), delay_seconds=0)

        retried = store.claim(worker_id="worker-2", lease_seconds=60)
        assert retried is not None
        assert retried.retry_count == 1
        assert retried.recovered is False


@pytest.mark.skipif(DATABASE_URL is None, reason="TEST_DATABASE_URL is not configured")
def test_reclaimed_lease_fences_the_stale_worker() -> None:
    with ConnectionPool(DATABASE_URL or "", min_size=1, max_size=2) as pool:
        store = DeliveryStore(pool)
        accepted = store.accept(
            verified=VerifiedWebhook(
                provider="generic-hmac",
                event_id="evt_lease_fence",
                timestamp=1_700_000_000,
                payload_sha256=hashlib.sha256(b"lease-fence").hexdigest(),
            ),
            event_type="incident.resolved",
            route_id="incident-report",
            route_config_version="test-v1",
            input_data={"type": "incident.resolved"},
        )
        stale = store.claim(worker_id="worker-stale", lease_seconds=60)
        assert stale is not None
        with psycopg.connect(DATABASE_URL) as connection:
            connection.execute(
                "UPDATE jobs SET lease_until = now() - interval '1 second' WHERE id = %s",
                (accepted.job_id,),
            )
        replacement = store.claim(worker_id="worker-replacement", lease_seconds=60)
        assert replacement is not None

        with pytest.raises(LeaseLostError):
            store.fail(job=stale, error=RuntimeError("stale write"))

        status = store.status(accepted.delivery_id)
        assert status is not None
        assert status["status"] == "processing"
