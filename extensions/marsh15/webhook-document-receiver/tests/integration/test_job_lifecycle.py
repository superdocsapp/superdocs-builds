import hashlib
import os

import psycopg
import pytest
from psycopg_pool import ConnectionPool

from app.persistence import DeliveryStore
from app.security import VerifiedWebhook
from scripts.migrate import migrate

DATABASE_URL = os.getenv("TEST_DATABASE_URL")


@pytest.mark.skipif(DATABASE_URL is None, reason="TEST_DATABASE_URL is not configured")
def test_worker_claim_and_completion_are_durable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL or "")
    from app.config import get_settings

    get_settings.cache_clear()
    migrate()
    body = b'{"type":"incident.resolved","incident_id":"inc_worker"}'
    verified = VerifiedWebhook(
        provider="generic-hmac",
        event_id="evt_worker",
        timestamp=1_700_000_000,
        payload_sha256=hashlib.sha256(body).hexdigest(),
    )

    with ConnectionPool(DATABASE_URL or "", min_size=1, max_size=2) as pool:
        store = DeliveryStore(pool)
        accepted = store.accept(
            verified=verified,
            event_type="incident.resolved",
            route_id="incident-report",
            route_config_version="test-v1",
            input_data={"type": "incident.resolved", "incident_id": "inc_worker"},
        )
        claimed = store.claim(worker_id="worker-test", lease_seconds=60)
        assert claimed is not None
        assert claimed.job_id == accepted.job_id
        assert claimed.input_data["incident_id"] == "inc_worker"
        assert store.claim(worker_id="worker-other", lease_seconds=60) is None

        store.complete(
            job=claimed,
            export_format="docx",
            filename="incident.docx",
            mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            content=b"docx-bytes",
            max_artifact_bytes=10_485_760,
            superdocs_session_id="session_1",
            superdocs_job_id="superdocs_job_1",
        )

    with psycopg.connect(DATABASE_URL) as connection:
        job_state = connection.execute(
            "SELECT state, leased_by, superdocs_job_id FROM jobs WHERE id = %s",
            (accepted.job_id,),
        ).fetchone()
        artifact = connection.execute(
            "SELECT byte_size, sha256 FROM artifacts WHERE delivery_id = %s",
            (accepted.delivery_id,),
        ).fetchone()
        assert job_state == ("completed", None, "superdocs_job_1")
        assert artifact == (10, hashlib.sha256(b"docx-bytes").hexdigest())

    get_settings.cache_clear()
