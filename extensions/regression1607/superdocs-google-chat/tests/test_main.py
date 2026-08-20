from fastapi.testclient import TestClient

from app import main
from app.config import settings


def _client():
    return TestClient(main.app)


def test_health_reports_config_and_auth_flags():
    r = _client().get("/health")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"ok", "configured", "auth_enforced"}


def test_webhook_rejects_forged_request_when_auth_enforced(monkeypatch):
    monkeypatch.setattr(settings, "chat_audience", "123456")
    r = _client().post("/", json={"type": "MESSAGE"})  # no signed Authorization header
    assert r.status_code == 401


def test_daily_digest_requires_token(monkeypatch):
    monkeypatch.setattr(settings, "digest_token", "s3cret")
    assert _client().post("/tasks/daily-digest").status_code == 403
    ok = _client().post("/tasks/daily-digest", params={"token": "s3cret"})
    assert ok.status_code == 200
    assert "digests" in ok.json()
