import hashlib
import os
from uuid import uuid4

import pytest
from psycopg_pool import ConnectionPool

from app.persistence import DeliveryStore, ReviewDecision
from app.security import VerifiedWebhook
from app.superdocs import PendingChange
from scripts.migrate import migrate

DATABASE_URL = os.getenv("TEST_DATABASE_URL")


@pytest.mark.skipif(DATABASE_URL is None, reason="TEST_DATABASE_URL is not configured")
def test_partial_decisions_survive_and_resume_only_when_complete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL or "")
    from app.config import get_settings

    get_settings.cache_clear()
    migrate()
    verified = VerifiedWebhook(
        provider="generic-hmac",
        event_id="evt_review",
        timestamp=1_700_000_000,
        payload_sha256=hashlib.sha256(b"review").hexdigest(),
    )
    with ConnectionPool(DATABASE_URL or "", min_size=1, max_size=2) as pool:
        store = DeliveryStore(pool)
        accepted = store.accept(
            verified=verified,
            event_type="incident.resolved",
            route_id="incident-report",
            route_config_version="test-v1",
            input_data={"type": "incident.resolved"},
        )
        first_claim = store.claim(worker_id="worker-review", lease_seconds=60)
        assert first_claim is not None
        store.save_started(
            job=first_claim,
            session_id="session_review",
            superdocs_job_id="superdocs_review",
        )
        review_claim = store.claim(worker_id="worker-review", lease_seconds=60)
        assert review_claim is not None
        store.save_review(
            job=review_claim,
            changes=(
                PendingChange("chg_1", "edit", "chunk_1", "old", "new", "Update"),
                PendingChange("chg_2", "delete", "chunk_2", "remove", None, "Remove"),
            ),
        )

        first_complete = store.submit_decisions(
            delivery_id=accepted.delivery_id,
            decisions=[ReviewDecision("chg_1", True)],
            actor_id="reviewer",
            batch_id=uuid4(),
        )
        assert first_complete is False
        assert store.claim(worker_id="worker-review", lease_seconds=60) is None

        second_complete = store.submit_decisions(
            delivery_id=accepted.delivery_id,
            decisions=[ReviewDecision("chg_2", False, "Keep this section")],
            actor_id="reviewer",
            batch_id=uuid4(),
        )
        assert second_complete is True
        approval_claim = store.claim(worker_id="worker-review", lease_seconds=60)
        assert approval_claim is not None
        assert approval_claim.external_wait_kind == "change_review"
        assert store.decision_payload(approval_claim) == [
            {"change_id": "chg_1", "approved": True},
            {"change_id": "chg_2", "approved": False, "feedback": "Keep this section"},
        ]

        changes = store.list_changes(accepted.delivery_id)
        assert [change["review_state"] for change in changes] == ["approved", "rejected"]

    get_settings.cache_clear()
