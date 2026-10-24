import asyncio
import hashlib
import hmac
import json
import os
import time
from typing import Literal

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg_pool import ConnectionPool

from app.config import get_settings
from app.main import app
from app.persistence import DeliveryStore
from app.superdocs import DocumentResult, JobSnapshot, StartedJob
from app.worker import run_once

DATABASE_URL = os.getenv("TEST_DATABASE_URL")
SECRET = "s" * 32
MANAGEMENT_HEADERS = {"Authorization": f"Bearer {'m' * 32}"}


class FakeSuperDocs:
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
        assert payload["incident_id"] == "inc_vertical"
        assert approval_mode == "ask_every_time"
        return StartedJob(session_id=f"webhook-{event_id}", job_id="superdocs_fake_1")

    async def get_job(self, job_id: str) -> JobSnapshot:
        return JobSnapshot(status="completed")

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
            filename="incident-report.docx",
            content=b"deterministic-docx",
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )


@pytest.mark.skipif(DATABASE_URL is None, reason="TEST_DATABASE_URL is not configured")
def test_signed_event_reaches_durable_artifact(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL or "")
    monkeypatch.setenv("SUPERDOCS_API_KEY", "test")
    monkeypatch.setenv("WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("JOB_POLL_INTERVAL_SECONDS", "0")
    get_settings.cache_clear()
    body = json.dumps(
        {"type": "incident.resolved", "incident_id": "inc_vertical"},
        separators=(",", ":"),
    ).encode()
    timestamp = str(int(time.time()))
    signature = hmac.new(
        SECRET.encode(),
        timestamp.encode() + b"." + b"evt_vertical" + b"." + body,
        hashlib.sha256,
    ).hexdigest()
    headers = {
        "Content-Type": "application/json",
        "X-Webhook-ID": "evt_vertical",
        "X-Webhook-Timestamp": timestamp,
        "X-Webhook-Signature": f"sha256={signature}",
    }

    with TestClient(app) as client:
        response = client.post("/v1/webhooks/generic-hmac", content=body, headers=headers)
        assert response.status_code == 202
        delivery_id = response.json()["delivery_id"]

        with ConnectionPool(DATABASE_URL or "", min_size=1, max_size=2) as pool:
            store = DeliveryStore(pool)
            started = asyncio.run(
                run_once(
                    store=store,
                    processor=FakeSuperDocs(),
                    settings=get_settings(),
                    worker_id="acceptance-worker",
                )
            )
            completed = asyncio.run(
                run_once(
                    store=store,
                    processor=FakeSuperDocs(),
                    settings=get_settings(),
                    worker_id="acceptance-worker",
                )
            )
        assert started is True
        assert completed is True

        status_response = client.get(
            f"/v1/deliveries/{delivery_id}", headers=MANAGEMENT_HEADERS
        )
        assert status_response.json()["status"] == "completed"
        artifact_response = client.get(
            f"/v1/deliveries/{delivery_id}/artifact", headers=MANAGEMENT_HEADERS
        )
        assert artifact_response.content == b"deterministic-docx"
        assert artifact_response.headers["x-artifact-sha256"] == hashlib.sha256(
            b"deterministic-docx"
        ).hexdigest()

    with psycopg.connect(DATABASE_URL) as connection:
        artifact = connection.execute(
            "SELECT filename, byte_size, sha256 FROM artifacts WHERE delivery_id = %s",
            (delivery_id,),
        ).fetchone()
        assert artifact == (
            "incident-report.docx",
            len(b"deterministic-docx"),
            hashlib.sha256(b"deterministic-docx").hexdigest(),
        )

    get_settings.cache_clear()
