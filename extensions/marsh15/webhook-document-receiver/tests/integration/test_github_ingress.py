import hashlib
import hmac
import json
import os

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app

DATABASE_URL = os.getenv("TEST_DATABASE_URL")
GITHUB_SECRET = "g" * 32


def github_headers(body: bytes, *, event: str, delivery_id: str) -> dict[str, str]:
    signature = hmac.new(GITHUB_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return {
        "Content-Type": "application/json",
        "X-Hub-Signature-256": f"sha256={signature}",
        "X-GitHub-Delivery": delivery_id,
        "X-GitHub-Event": event,
    }


@pytest.mark.skipif(DATABASE_URL is None, reason="TEST_DATABASE_URL is not configured")
def test_github_release_uses_header_semantics_and_route_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL or "")
    monkeypatch.setenv("SUPERDOCS_API_KEY", "test")
    monkeypatch.setenv("WEBHOOK_SECRET", "s" * 32)
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", GITHUB_SECRET)
    monkeypatch.setenv("MANAGEMENT_TOKEN", "m" * 32)
    get_settings.cache_clear()
    body = json.dumps(
        {
            "action": "published",
            "release": {"tag_name": "v1.2.3"},
            "repository": {"full_name": "example/project"},
            "sender": {"login": "not-persisted"},
        },
        separators=(",", ":"),
    ).encode()

    with TestClient(app) as client:
        response = client.post(
            "/v1/webhooks/github",
            content=body,
            headers=github_headers(body, event="release", delivery_id="github-release-1"),
        )
        assert response.status_code == 202
        accepted = response.json()
        job_id = response.json()["job_id"]

        replay = client.post(
            "/v1/webhooks/github",
            content=body,
            headers=github_headers(body, event="release", delivery_id="github-release-2"),
        )
        assert replay.status_code == 202
        assert replay.json() == {**accepted, "duplicate": True}

        ping_body = b'{"zen":"Keep it logically awesome."}'
        ping = client.post(
            "/v1/webhooks/github",
            content=ping_body,
            headers=github_headers(ping_body, event="ping", delivery_id="github-ping-1"),
        )
        assert ping.status_code == 202
        assert ping.json()["status"] == "pong"

    with psycopg.connect(DATABASE_URL) as connection:
        stored = connection.execute(
            """
            SELECT d.provider, d.event_type, d.route_id, j.input_data, j.route_config
            FROM jobs j JOIN deliveries d ON d.id = j.delivery_id
            WHERE j.id = %s
            """,
            (job_id,),
        ).fetchone()
        assert stored is not None
        assert stored[0:3] == ("github", "release.published", "github-release-notes")
        assert "sender" not in stored[3]
        assert stored[4]["export"]["format"] == "docx"
        delivery_count = connection.execute(
            "SELECT count(*) FROM deliveries WHERE provider = 'github'"
        ).fetchone()
        assert delivery_count == (1,)

    get_settings.cache_clear()
