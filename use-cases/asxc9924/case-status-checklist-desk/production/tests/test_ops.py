import json
import logging

import pytest


def test_rate_limiter_blocks_after_limit():
    from case_status_desk.rate_limit import InMemoryRateLimiter

    limiter = InMemoryRateLimiter(limit=3, window_s=60)
    key = "key:sk_test"
    results = [limiter.allow(key)[0] for _ in range(5)]
    assert results == [True, True, True, False, False]


def test_rate_limiter_resets_after_window(monkeypatch):
    from case_status_desk.rate_limit import InMemoryRateLimiter
    import case_status_desk.rate_limit as rl_module

    limiter = InMemoryRateLimiter(limit=1, window_s=10)
    fake_time = [1000.0]
    monkeypatch.setattr(rl_module.time, "monotonic", lambda: fake_time[0])

    allowed1, _ = limiter.allow("k")
    allowed2, retry_after = limiter.allow("k")
    assert allowed1 is True
    assert allowed2 is False
    assert retry_after > 0

    fake_time[0] += 11  # past the window
    allowed3, _ = limiter.allow("k")
    assert allowed3 is True


def test_rate_limit_middleware_returns_429(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from case_status_desk.rate_limit import RateLimitMiddleware
    import case_status_desk.rate_limit as rl_module

    # tiny limit so the test doesn't need 60 requests
    monkeypatch.setattr(rl_module, "_limiter", rl_module.InMemoryRateLimiter(limit=2, window_s=60))

    app = FastAPI()
    app.add_middleware(RateLimitMiddleware)

    @app.get("/thing")
    def thing():
        return {"ok": True}

    client = TestClient(app)
    r1 = client.get("/thing", headers={"Authorization": "Bearer sk_x"})
    r2 = client.get("/thing", headers={"Authorization": "Bearer sk_x"})
    r3 = client.get("/thing", headers={"Authorization": "Bearer sk_x"})
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r3.status_code == 429
    assert "Retry-After" in r3.headers


def test_rate_limit_middleware_skips_healthz(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from case_status_desk.rate_limit import RateLimitMiddleware
    import case_status_desk.rate_limit as rl_module

    monkeypatch.setattr(rl_module, "_limiter", rl_module.InMemoryRateLimiter(limit=1, window_s=60))

    app = FastAPI()
    app.add_middleware(RateLimitMiddleware)

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    client = TestClient(app)
    for _ in range(5):
        assert client.get("/healthz").status_code == 200


def test_json_formatter_produces_valid_json_with_expected_fields():
    from case_status_desk.logging_setup import JsonFormatter, request_id_var

    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="test.logger", level=logging.INFO, pathname=__file__, lineno=1,
        msg="something happened", args=(), exc_info=None,
    )
    record.status_code = 200
    record.duration_ms = 12.3

    token = request_id_var.set("abc123")
    try:
        line = formatter.format(record)
    finally:
        request_id_var.reset(token)

    parsed = json.loads(line)
    assert parsed["message"] == "something happened"
    assert parsed["level"] == "INFO"
    assert parsed["request_id"] == "abc123"
    assert parsed["status_code"] == 200
    assert parsed["duration_ms"] == 12.3


def test_request_id_header_present_on_responses():
    from fastapi.testclient import TestClient
    from case_status_desk.app import app

    client = TestClient(app)
    r = client.get("/healthz")
    assert r.status_code == 200
    assert "X-Request-ID" in r.headers
    assert len(r.headers["X-Request-ID"]) == 16


def test_sso_disabled_by_default(monkeypatch):
    monkeypatch.delenv("OIDC_ISSUER", raising=False)
    monkeypatch.delenv("OIDC_AUDIENCE", raising=False)
    import importlib
    from case_status_desk import sso
    importlib.reload(sso)
    assert sso.SSO_ENABLED is False

    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        sso.require_sso_user(authorization="Bearer whatever")
    assert exc.value.status_code == 500
    assert "not configured" in exc.value.detail


def test_require_staff_user_falls_back_to_api_keys_when_sso_unset(monkeypatch):
    monkeypatch.delenv("OIDC_ISSUER", raising=False)
    monkeypatch.setenv("STAFF_API_KEYS", "sk_good:Alice:admin")
    import importlib
    from case_status_desk import sso, auth
    importlib.reload(sso)
    importlib.reload(auth)

    user = auth.require_staff_user(authorization="Bearer sk_good")
    assert user.name == "Alice"


def test_role_map_translates_idp_group_names():
    import importlib
    from case_status_desk import sso
    import os
    os.environ["OIDC_ROLE_MAP"] = "Immigration-Attorneys:approver,Immigration-Paralegals:preparer"
    importlib.reload(sso)
    try:
        assert sso._map_role(["Immigration-Attorneys"]) == "approver"
        assert sso._map_role(["Immigration-Paralegals"]) == "preparer"
        assert sso._map_role(["Some-Unmapped-Group"]) == "preparer"  # fails closed
    finally:
        del os.environ["OIDC_ROLE_MAP"]
        importlib.reload(sso)
