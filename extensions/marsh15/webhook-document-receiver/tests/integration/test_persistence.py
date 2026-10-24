import hashlib
import os
from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest
from psycopg_pool import ConnectionPool

from app.persistence import DeliveryCollisionError, DeliveryStore
from app.security import VerifiedWebhook
from scripts.migrate import migrate

DATABASE_URL = os.getenv("TEST_DATABASE_URL")


def verified(payload: bytes) -> VerifiedWebhook:
    return VerifiedWebhook(
        provider="generic-hmac",
        event_id="evt_123",
        timestamp=1_700_000_000,
        payload_sha256=hashlib.sha256(payload).hexdigest(),
    )


@pytest.mark.skipif(DATABASE_URL is None, reason="TEST_DATABASE_URL is not configured")
def test_accept_is_atomic_and_detects_delivery_collisions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL or "")
    from app.config import get_settings

    get_settings.cache_clear()
    migrate()

    with ConnectionPool(DATABASE_URL or "", min_size=1, max_size=2) as pool:
        store = DeliveryStore(pool)
        first = store.accept(
            verified=verified(b'{"type":"incident.resolved"}'),
            event_type="incident.resolved",
            route_id="incident-report",
            route_config_version="test-v1",
            input_data={"type": "incident.resolved"},
        )
        replay = store.accept(
            verified=verified(b'{"type":"incident.resolved"}'),
            event_type="incident.resolved",
            route_id="incident-report",
            route_config_version="test-v1",
            input_data={"type": "incident.resolved"},
        )

        assert first.duplicate is False
        assert replay.duplicate is True
        assert replay.delivery_id == first.delivery_id
        assert replay.job_id == first.job_id

        with pytest.raises(DeliveryCollisionError):
            store.accept(
                verified=verified(b'{"type":"incident.changed"}'),
                event_type="incident.changed",
                route_id="incident-report",
                route_config_version="test-v1",
                input_data={"type": "incident.changed"},
            )

    with psycopg.connect(DATABASE_URL) as connection:
        delivery_count = connection.execute(
            "SELECT count(*) FROM deliveries WHERE external_delivery_id = 'evt_123'"
        ).fetchone()
        job_count = connection.execute(
            """
            SELECT count(*)
            FROM jobs j
            JOIN deliveries d ON d.id = j.delivery_id
            WHERE d.external_delivery_id = 'evt_123'
            """
        ).fetchone()
        assert delivery_count == (1,)
        assert job_count == (1,)
        collision_audit = connection.execute(
            """
            SELECT reason_code, actor_type
            FROM delivery_transitions
            WHERE delivery_id = %s AND reason_code = 'delivery_id_collision'
            """,
            (first.delivery_id,),
        ).fetchall()
        assert collision_audit == [("delivery_id_collision", "ingress")]

    get_settings.cache_clear()


@pytest.mark.skipif(DATABASE_URL is None, reason="TEST_DATABASE_URL is not configured")
def test_fifty_concurrent_replays_create_one_delivery_and_job() -> None:
    with ConnectionPool(DATABASE_URL or "", min_size=1, max_size=20) as pool:
        store = DeliveryStore(pool)

        def accept_once(_: int):
            return store.accept(
                verified=verified(b'{"type":"incident.resolved"}'),
                event_type="incident.resolved",
                route_id="incident-report",
                route_config_version="test-v1",
                input_data={"type": "incident.resolved"},
            )

        with ThreadPoolExecutor(max_workers=20) as executor:
            accepted = list(executor.map(accept_once, range(50)))

    assert len({item.delivery_id for item in accepted}) == 1
    assert len({item.job_id for item in accepted}) == 1
    assert sum(not item.duplicate for item in accepted) == 1
    with psycopg.connect(DATABASE_URL or "") as connection:
        assert connection.execute("SELECT count(*) FROM deliveries").fetchone() == (1,)
        assert connection.execute("SELECT count(*) FROM jobs").fetchone() == (1,)
