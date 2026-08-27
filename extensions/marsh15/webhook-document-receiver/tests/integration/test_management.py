import hashlib
import os

import pytest
from fastapi.testclient import TestClient
from psycopg_pool import ConnectionPool

from app.main import app
from app.persistence import DeliveryStore
from app.security import VerifiedWebhook
from app.superdocs import PendingChange

DATABASE_URL = os.getenv("TEST_DATABASE_URL")
MANAGEMENT_HEADERS = {"Authorization": f"Bearer {'m' * 32}"}


@pytest.mark.skipif(DATABASE_URL is None, reason="TEST_DATABASE_URL is not configured")
def test_management_token_guards_review_and_persists_item_decisions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL or "")
    monkeypatch.setenv("SUPERDOCS_API_KEY", "test")
    monkeypatch.setenv("WEBHOOK_SECRET", "s" * 32)
    monkeypatch.setenv("MANAGEMENT_TOKEN", "m" * 32)
    from app.config import get_settings

    get_settings.cache_clear()
    with ConnectionPool(DATABASE_URL or "", min_size=1, max_size=2) as pool:
        store = DeliveryStore(pool)
        accepted = store.accept(
            verified=VerifiedWebhook(
                provider="generic-hmac",
                event_id="evt_management",
                timestamp=1_700_000_000,
                payload_sha256=hashlib.sha256(b"management").hexdigest(),
            ),
            event_type="incident.resolved",
            route_id="incident-report",
            route_config_version="test-v1",
            input_data={"type": "incident.resolved"},
        )
        started = store.claim(worker_id="management-test", lease_seconds=60)
        assert started is not None
        store.save_started(
            job=started,
            session_id="session_management",
            superdocs_job_id="superdocs_management",
        )
        polling = store.claim(worker_id="management-test", lease_seconds=60)
        assert polling is not None
        store.save_review(
            job=polling,
            changes=(
                PendingChange("chg_keep", "edit", "chunk_1", "old", "new", "Update"),
                PendingChange("chg_drop", "delete", "chunk_2", "old", None, "Delete"),
            ),
        )

    with TestClient(app) as client:
        path = f"/v1/deliveries/{accepted.delivery_id}/changes"
        assert client.get(path).status_code == 401
        webhook_credentials = {"Authorization": f"Bearer {'s' * 32}"}
        assert client.get(path, headers=webhook_credentials).status_code == 401
        changes = client.get(path, headers=MANAGEMENT_HEADERS)
        assert changes.status_code == 200
        assert len(changes.json()["changes"]) == 2

        decision_response = client.post(
            f"/v1/deliveries/{accepted.delivery_id}/decisions",
            headers=MANAGEMENT_HEADERS,
            json={
                "decisions": [
                    {"change_id": "chg_keep", "approved": True},
                    {
                        "change_id": "chg_drop",
                        "approved": False,
                        "reason": "Deletion is not justified",
                    },
                ]
            },
        )
        assert decision_response.status_code == 200
        assert decision_response.json()["all_resolved"] is True
        states = {
            change["change_id"]: change["review_state"]
            for change in decision_response.json()["changes"]
        }
        assert states == {"chg_keep": "approved", "chg_drop": "rejected"}

    get_settings.cache_clear()


@pytest.mark.skipif(DATABASE_URL is None, reason="TEST_DATABASE_URL is not configured")
def test_manual_retry_allows_failed_job_but_not_active_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL or "")
    monkeypatch.setenv("SUPERDOCS_API_KEY", "test")
    monkeypatch.setenv("WEBHOOK_SECRET", "s" * 32)
    monkeypatch.setenv("MANAGEMENT_TOKEN", "m" * 32)
    from app.config import get_settings

    get_settings.cache_clear()
    with ConnectionPool(DATABASE_URL or "", min_size=1, max_size=2) as pool:
        store = DeliveryStore(pool)
        failed_delivery = store.accept(
            verified=VerifiedWebhook(
                provider="generic-hmac",
                event_id="evt_retry_failed",
                timestamp=1_700_000_000,
                payload_sha256=hashlib.sha256(b"retry-failed").hexdigest(),
            ),
            event_type="incident.resolved",
            route_id="incident-report",
            route_config_version="test-v1",
            input_data={"type": "incident.resolved"},
        )
        failed_job = store.claim(worker_id="retry-test", lease_seconds=60)
        assert failed_job is not None
        store.fail(job=failed_job, error=RuntimeError("terminal test failure"))

        active_delivery = store.accept(
            verified=VerifiedWebhook(
                provider="generic-hmac",
                event_id="evt_retry_active",
                timestamp=1_700_000_000,
                payload_sha256=hashlib.sha256(b"retry-active").hexdigest(),
            ),
            event_type="incident.resolved",
            route_id="incident-report",
            route_config_version="test-v1",
            input_data={"type": "incident.resolved"},
        )

    with TestClient(app) as client:
        failed_path = f"/v1/deliveries/{failed_delivery.delivery_id}/retry"
        assert client.post(failed_path).status_code == 401
        retried = client.post(failed_path, headers=MANAGEMENT_HEADERS)
        assert retried.status_code == 200
        assert retried.json()["status"] == "queued"
        assert retried.json()["resume_mode"] == "start_new"

        active = client.post(
            f"/v1/deliveries/{active_delivery.delivery_id}/retry",
            headers=MANAGEMENT_HEADERS,
        )
        assert active.status_code == 409
        assert "not safe to retry" in active.json()["detail"]

        transitions = client.get(
            f"/v1/deliveries/{failed_delivery.delivery_id}/transitions",
            headers=MANAGEMENT_HEADERS,
        ).json()["transitions"]
        assert transitions[-1]["reason_code"] == "manual_retry"
        assert transitions[-1]["actor_type"] == "administrator"

    get_settings.cache_clear()
