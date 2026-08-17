import os

os.environ["SUPERDOCS_API_KEY"] = "test-key"

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway.audit import DEFAULT_AUDIT_LOGGER
from app.gateway.client import DownstreamUnavailableError
from app.gateway.quota import DEFAULT_QUOTA_MANAGER, TeamQuota
from app.routes.gateway import client as downstream_client, router

app = FastAPI()
app.include_router(router)
http = TestClient(app)


def reset_state():
    DEFAULT_AUDIT_LOGGER.events.clear()
    DEFAULT_QUOTA_MANAGER.quotas.clear()
    DEFAULT_QUOTA_MANAGER.quotas["default"] = TeamQuota(limit=100)


def test_chat_clean_request_is_forwarded(monkeypatch):
    reset_state()
    class FakeResponse:
        status_code = 200; text = ""; headers = {}
        def json(self): return {"session_id": "test-session"}
    async def fake_request(**kwargs):
        assert kwargs["path"] == "/v1/chat"
        return FakeResponse()
    monkeypatch.setattr(downstream_client, "request", fake_request)
    response = http.post("/gateway/v1/chat", json={"message": "Update title.", "document_html": "<h1>Policy</h1>"})
    assert response.status_code == 200
    assert response.json()["session_id"] == "test-session"
    assert DEFAULT_AUDIT_LOGGER.events[0].allowed is True


def test_chat_sensitive_is_blocked_before_quota(monkeypatch):
    reset_state()
    DEFAULT_QUOTA_MANAGER.quotas["default"] = TeamQuota(limit=1)
    async def fail(**kwargs): raise AssertionError("downstream must not be called")
    monkeypatch.setattr(downstream_client, "request", fail)
    response = http.post("/gateway/v1/chat", json={"message": "john@example.com"})
    assert response.status_code == 403
    assert response.json()["detail"]["error"] == "SENSITIVE_CONTENT_BLOCKED"
    assert DEFAULT_QUOTA_MANAGER.quotas["default"].used == 0


def test_upload_clean_file_is_forwarded(monkeypatch):
    reset_state()
    class FakeResponse:
        status_code = 200; text = ""; headers = {}
        def json(self): return {"document_id": "doc-1"}
    async def fake_request(**kwargs):
        assert kwargs["path"] == "/v1/documents/upload"
        filename, content, content_type = kwargs["files"]["file"]
        assert filename == "policy.txt"
        assert content_type == "text/plain"
        assert content.read() == b"Project deadline: July 15, 2026."
        return FakeResponse()
    monkeypatch.setattr(downstream_client, "request", fake_request)
    response = http.post("/gateway/v1/documents/upload", files={"file": ("policy.txt", b"Project deadline: July 15, 2026.", "text/plain")})
    assert response.status_code == 200


def test_upload_sensitive_is_blocked(monkeypatch):
    reset_state()
    async def fail(**kwargs): raise AssertionError("downstream must not be called")
    monkeypatch.setattr(downstream_client, "request", fail)
    response = http.post("/gateway/v1/documents/upload", files={"file": ("policy.txt", b"Contact john@example.com", "text/plain")})
    assert response.status_code == 403
    assert response.json()["detail"]["error"] == "SENSITIVE_CONTENT_BLOCKED"


def test_approve_sensitive_is_blocked(monkeypatch):
    reset_state()
    async def fail(**kwargs): raise AssertionError("downstream must not be called")
    monkeypatch.setattr(downstream_client, "request", fail)
    response = http.post("/gateway/v1/chat/session/approve", json={"comment": "john@example.com"})
    assert response.status_code == 403


def test_export_sensitive_is_blocked(monkeypatch):
    reset_state()
    async def fail(**kwargs): raise AssertionError("downstream must not be called")
    monkeypatch.setattr(downstream_client, "request", fail)
    response = http.post("/gateway/v1/documents/export", json={"html": "Contact john@example.com"})
    assert response.status_code == 403


def test_quota_exceeded_is_blocked():
    reset_state()
    DEFAULT_QUOTA_MANAGER.quotas["default"] = TeamQuota(limit=0)
    response = http.post("/gateway/v1/documents/export", json={"html": "Policy"})
    assert response.status_code == 429
    assert response.json()["detail"]["error"] == "TEAM_QUOTA_EXCEEDED"


def test_downstream_unavailable_returns_503(monkeypatch):
    reset_state()
    async def fail(**kwargs): raise DownstreamUnavailableError("unavailable")
    monkeypatch.setattr(downstream_client, "request", fail)
    response = http.post("/gateway/v1/chat", json={"message": "Update title"})
    assert response.status_code == 503
    assert response.json()["detail"]["error"] == "DOWNSTREAM_UNAVAILABLE"


def test_upload_quota_is_not_consumed_for_sensitive_content():
    reset_state()
    DEFAULT_QUOTA_MANAGER.quotas["default"] = TeamQuota(limit=1)
    response = http.post(
        "/gateway/v1/documents/upload",
        files={"file": ("policy.txt", b"john@example.com", "text/plain")},
    )
    assert response.status_code == 403
    assert DEFAULT_QUOTA_MANAGER.quotas["default"].used == 0
