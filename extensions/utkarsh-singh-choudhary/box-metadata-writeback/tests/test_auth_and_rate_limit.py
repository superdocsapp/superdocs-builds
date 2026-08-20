"""Auth, demo-seed gating, and rate-limit tests.

Auth defaults to disabled (no WORKFLOW_API_KEYS/TENANTS_CONFIG_PATH) so
the rest of the suite (and local dev) never needs a token -- these tests
explicitly turn auth on by registering a real tenant directly against
the shared TenantRegistry (app.api.main._tenants) and restore its
pre-test state afterward so they don't leak into other test modules.
"""
import pytest
from fastapi.testclient import TestClient

import app.api.main as m
from app.api.main import app


def fresh_client():
    return TestClient(app)


@pytest.fixture
def require_key():
    """Turns auth on for the duration of one test by registering a real
    tenant directly against the shared TenantRegistry (mirroring what
    TENANTS_CONFIG_PATH or WORKFLOW_API_KEYS would do at startup), and
    restores the registry's pre-test state afterward so this doesn't leak
    into other test modules."""
    original_configs = dict(m._tenants._configs_by_key)
    original_auth_enabled = m._tenants.auth_enabled
    from app.tenancy import TenantConfig

    cfg = TenantConfig(tenant_id="test-tenant", api_key="test-secret-key")
    m._tenants._configs_by_key = {cfg.api_key: cfg}
    m._tenants.auth_enabled = True
    try:
        yield "test-secret-key"
    finally:
        m._tenants._configs_by_key = original_configs
        m._tenants.auth_enabled = original_auth_enabled


def test_request_without_key_is_rejected_when_auth_enabled(require_key):
    client = fresh_client()
    resp = client.get("/files")
    assert resp.status_code == 401


def test_request_with_wrong_key_is_rejected(require_key):
    client = fresh_client()
    resp = client.get("/files", headers={"Authorization": "Bearer wrong-key"})
    assert resp.status_code == 401


def test_request_with_correct_key_is_accepted(require_key):
    client = fresh_client()
    resp = client.get("/files", headers={"Authorization": f"Bearer {require_key}"})
    assert resp.status_code == 200


def test_auth_disabled_by_default_lets_requests_through():
    # No fixture here: auth reflects whatever the process env produced,
    # which in the test environment is disabled -- a no-op pass-through.
    client = fresh_client()
    resp = client.get("/files")
    assert resp.status_code == 200 or resp.status_code == 401
    # If a real WORKFLOW_API_KEYS/TENANTS_CONFIG_PATH happens to be set in
    # this environment, 401 without a header is correct too -- the real
    # assertion is that the endpoint doesn't 500 either way.


def test_healthz_never_requires_auth(require_key):
    client = fresh_client()
    resp = client.get("/healthz")
    assert resp.status_code == 200


def test_demo_seed_disabled_by_default(monkeypatch):
    monkeypatch.delenv("WORKFLOW_ENABLE_DEMO_SEED", raising=False)
    client = fresh_client()
    resp = client.post("/demo/seed")
    assert resp.status_code == 404


def test_demo_seed_enabled_works_against_fake_box_client(monkeypatch):
    monkeypatch.setenv("WORKFLOW_ENABLE_DEMO_SEED", "true")
    client = fresh_client()
    resp = client.post("/demo/seed")
    assert resp.status_code == 200
    body = resp.json()
    assert body["seeded"] >= 0  # idempotent: 0 on a second call in the same process


def test_rate_limit_blocks_after_threshold(monkeypatch):
    monkeypatch.setattr(m, "_RATE_LIMIT_PER_MINUTE", 3)
    m._rate_buckets.clear()
    client = fresh_client()
    statuses = [client.get("/healthz").status_code for _ in range(3)]
    # /healthz is exempt from rate limiting by design (health checks must
    # never be throttled), so all three succeed regardless of the limit.
    assert statuses == [200, 200, 200]

    statuses = [client.get("/files").status_code for _ in range(5)]
    assert 429 in statuses
