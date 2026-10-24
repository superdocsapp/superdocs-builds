import asyncio
import hashlib
import hmac
import json
import os
import time
from typing import Literal

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.superdocs import DocumentResult, JobSnapshot, PendingChange, StartedJob
from app.worker import run_once

DATABASE_URL = os.getenv("TEST_DATABASE_URL")
SECRET = "s" * 32
MANAGEMENT_HEADERS = {"Authorization": f"Bearer {'m' * 32}"}


class FakeManualSuperDocs:
    def __init__(self) -> None:
        self.submitted_decisions: list[dict[str, object]] | None = None

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
        assert approval_mode == "ask_every_time"
        return StartedJob(session_id="session_manual", job_id="superdocs_manual")

    async def get_job(self, job_id: str) -> JobSnapshot:
        if self.submitted_decisions is None:
            return JobSnapshot(
                status="awaiting_approval",
                awaiting_kind="change_review",
                pending_changes=(
                    PendingChange(
                        "chg_approve", "edit", "chunk_1", "old", "new", "Update status"
                    ),
                    PendingChange(
                        "chg_reject", "delete", "chunk_2", "remove", None, "Remove section"
                    ),
                ),
            )
        return JobSnapshot(status="completed")

    async def submit_decisions(
        self,
        *,
        session_id: str,
        job_id: str,
        decisions: list[dict[str, object]],
    ) -> None:
        self.submitted_decisions = decisions

    async def continue_job(self, *, session_id: str, job_id: str) -> None:
        raise AssertionError("Change review must not call the continuation endpoint")

    async def export(
        self,
        *,
        event_id: str,
        session_id: str,
        job_id: str,
        export_format: str | None = None,
    ) -> DocumentResult:
        return DocumentResult(
            session_id=session_id,
            job_id=job_id,
            filename="reviewed-incident.docx",
            content=b"reviewed-docx",
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )


@pytest.mark.skipif(DATABASE_URL is None, reason="TEST_DATABASE_URL is not configured")
def test_manual_item_review_blocks_then_resumes_export(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL or "")
    monkeypatch.setenv("SUPERDOCS_API_KEY", "test")
    monkeypatch.setenv("WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("MANAGEMENT_TOKEN", "m" * 32)
    monkeypatch.setenv("JOB_POLL_INTERVAL_SECONDS", "0")
    get_settings.cache_clear()

    body = json.dumps(
        {"type": "incident.resolved", "incident_id": "inc_manual"},
        separators=(",", ":"),
    ).encode()
    timestamp = str(int(time.time()))
    signature = hmac.new(
        SECRET.encode(),
        timestamp.encode() + b"." + b"evt_manual" + b"." + body,
        hashlib.sha256,
    ).hexdigest()
    headers = {
        "Content-Type": "application/json",
        "X-Webhook-ID": "evt_manual",
        "X-Webhook-Timestamp": timestamp,
        "X-Webhook-Signature": f"sha256={signature}",
    }
    processor = FakeManualSuperDocs()

    with TestClient(app) as client:
        accepted = client.post("/v1/webhooks/generic-hmac", content=body, headers=headers)
        assert accepted.status_code == 202
        delivery_id = accepted.json()["delivery_id"]

        for _ in range(2):
            assert asyncio.run(
                run_once(
                    store=app.state.deliveries,
                    processor=processor,
                    settings=get_settings(),
                    worker_id="manual-worker",
                )
            )

        before_decision = client.get(
            f"/v1/deliveries/{delivery_id}", headers=MANAGEMENT_HEADERS
        )
        assert before_decision.json()["status"] == "awaiting_approval"
        assert client.get(
            f"/v1/deliveries/{delivery_id}/artifact", headers=MANAGEMENT_HEADERS
        ).status_code == 404

        decision_response = client.post(
            f"/v1/deliveries/{delivery_id}/decisions",
            headers=MANAGEMENT_HEADERS,
            json={
                "decisions": [
                    {"change_id": "chg_approve", "approved": True},
                    {
                        "change_id": "chg_reject",
                        "approved": False,
                        "reason": "Retain the evidence section",
                    },
                ]
            },
        )
        assert decision_response.status_code == 200

        for _ in range(2):
            assert asyncio.run(
                run_once(
                    store=app.state.deliveries,
                    processor=processor,
                    settings=get_settings(),
                    worker_id="manual-worker",
                )
            )

        completed = client.get(
            f"/v1/deliveries/{delivery_id}", headers=MANAGEMENT_HEADERS
        )
        assert completed.json()["status"] == "completed"
        artifact = client.get(
            f"/v1/deliveries/{delivery_id}/artifact", headers=MANAGEMENT_HEADERS
        )
        assert artifact.content == b"reviewed-docx"
        timeline = client.get(
            f"/v1/deliveries/{delivery_id}/transitions", headers=MANAGEMENT_HEADERS
        ).json()["transitions"]
        assert [transition["next_state"] for transition in timeline] == [
            "queued",
            "processing",
            "starting_superdocs",
            "processing",
            "awaiting_approval",
            "approving",
            "processing",
            # A second approving transition is the durable external-action marker.
            # If the process dies after this point, recovery stops for reconciliation
            # rather than submitting the same decisions twice.
            "approving",
            "processing",
            "exporting",
            "completed",
        ]

    assert processor.submitted_decisions == [
        {"change_id": "chg_approve", "approved": True},
        {
            "change_id": "chg_reject",
            "approved": False,
            "feedback": "Retain the evidence section",
        },
    ]
    get_settings.cache_clear()
