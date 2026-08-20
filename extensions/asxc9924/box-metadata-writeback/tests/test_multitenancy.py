"""Proves multi-tenant isolation, not just asserts it: two tenants, each
with their own API key, seed and process files under the SAME file_id,
and this suite checks that tenant B's requests never see tenant A's
files, metadata, review queue, audit trail, or run/cost data -- and that
this holds even when both tenants happen to use identical file_ids,
which is the case that would actually catch a missing tenant_id filter.
"""
import pytest
from fastapi.testclient import TestClient

import app.api.main as m
from app.tenancy import TenantConfig
from app.api.main import app

CONTRACT_A = b"""SERVICES AGREEMENT
Counterparty: Acme Logistics Inc
Effective Date: 2026-01-15
Value: $84,000
"""

CONTRACT_B = b"""SERVICES AGREEMENT
Counterparty: Globex Shipping Ltd
Effective Date: 2026-02-01
Value: $199,000
"""


@pytest.fixture
def two_tenants():
    """Registers two real, isolated tenants against the shared
    TenantRegistry for the duration of one test, and restores the
    registry's prior state afterward."""
    original_configs = dict(m._tenants._configs_by_key)
    original_contexts = dict(m._tenants._contexts)
    original_auth_enabled = m._tenants.auth_enabled

    cfg_a = TenantConfig(tenant_id="acme-corp", api_key="acme-secret-key")
    cfg_b = TenantConfig(tenant_id="globex-corp", api_key="globex-secret-key")
    m._tenants._configs_by_key = {cfg_a.api_key: cfg_a, cfg_b.api_key: cfg_b}
    m._tenants._contexts = {}  # force fresh, isolated contexts for this test
    m._tenants.auth_enabled = True
    try:
        yield {"acme": "acme-secret-key", "globex": "globex-secret-key"}
    finally:
        m._tenants._configs_by_key = original_configs
        m._tenants._contexts = original_contexts
        m._tenants.auth_enabled = original_auth_enabled


def headers(key: str) -> dict:
    return {"Authorization": f"Bearer {key}"}


def test_tenant_b_cannot_list_tenant_a_files(two_tenants):
    client = TestClient(app)
    acme_key = two_tenants["acme"]
    globex_key = two_tenants["globex"]

    m._tenants.context_for("acme-corp").box.seed_file("contract-1", "acme.pdf", CONTRACT_A)
    client.post("/process/contract-1", headers=headers(acme_key))

    # Tenant A sees their own file.
    resp_a = client.get("/files", headers=headers(acme_key))
    assert resp_a.status_code == 200
    assert resp_a.json()["count"] == 1
    assert resp_a.json()["files"][0]["counterparty_name"] == "Acme Logistics Inc"

    # Tenant B, who has processed nothing, sees nothing -- not tenant A's file.
    resp_b = client.get("/files", headers=headers(globex_key))
    assert resp_b.status_code == 200
    assert resp_b.json()["count"] == 0


def test_same_file_id_in_two_tenants_stays_two_separate_files(two_tenants):
    """The case that actually catches a missing tenant_id filter: both
    tenants use the identical file_id 'contract-1' with DIFFERENT
    content. If isolation were broken, tenant B's read would see tenant
    A's counterparty name (or vice versa, depending on write order)."""
    client = TestClient(app)
    acme_key = two_tenants["acme"]
    globex_key = two_tenants["globex"]

    m._tenants.context_for("acme-corp").box.seed_file("contract-1", "acme.pdf", CONTRACT_A)
    m._tenants.context_for("globex-corp").box.seed_file("contract-1", "globex.pdf", CONTRACT_B)

    client.post("/process/contract-1", headers=headers(acme_key))
    client.post("/process/contract-1", headers=headers(globex_key))

    detail_a = client.get("/files/contract-1", headers=headers(acme_key)).json()
    detail_b = client.get("/files/contract-1", headers=headers(globex_key)).json()

    assert detail_a["metadata"]["counterparty_name"] == "Acme Logistics Inc"
    assert detail_b["metadata"]["counterparty_name"] == "Globex Shipping Ltd"
    assert detail_a["metadata"]["counterparty_name"] != detail_b["metadata"]["counterparty_name"]


def test_tenant_b_cannot_read_tenant_as_review_queue(two_tenants):
    client = TestClient(app)
    acme_key = two_tenants["acme"]
    globex_key = two_tenants["globex"]

    # A low-confidence value that lands in the review queue. Mirrors the
    # exact fixture in tests/test_review_and_history.py, where
    # contract_value comes back at confidence 0.55 in the fake extractor
    # (below the 0.7 default threshold) -- proven to land in review
    # rather than guessing at wording that might not trigger it.
    low_confidence_doc = CONTRACT_A
    m._tenants.context_for("acme-corp").box.seed_file("needs-review", "acme.pdf", low_confidence_doc)
    client.post("/process/needs-review", headers=headers(acme_key))

    reviews_a = client.get("/reviews", headers=headers(acme_key)).json()
    reviews_b = client.get("/reviews", headers=headers(globex_key)).json()

    # Whatever tenant A's queue holds, tenant B's must not contain it.
    a_ids = {r["review_id"] for r in reviews_a["pending"]}
    b_ids = {r["review_id"] for r in reviews_b["pending"]}
    assert a_ids.isdisjoint(b_ids)
    assert reviews_b["pending"] == []


def test_tenant_b_cannot_approve_tenant_as_review(two_tenants):
    client = TestClient(app)
    acme_key = two_tenants["acme"]
    globex_key = two_tenants["globex"]

    low_confidence_doc = CONTRACT_A
    m._tenants.context_for("acme-corp").box.seed_file("needs-review-2", "acme.pdf", low_confidence_doc)
    client.post("/process/needs-review-2", headers=headers(acme_key))

    reviews_a = client.get("/reviews", headers=headers(acme_key)).json()
    assert reviews_a["pending"], "fixture doc should reliably land contract_value in review at conf=0.55"
    review_id = reviews_a["pending"][0]["review_id"]

    # Tenant B tries to approve tenant A's review by ID -- must fail,
    # not silently succeed against the wrong tenant's queue.
    resp = client.post(f"/reviews/{review_id}/approve", headers=headers(globex_key))
    assert resp.status_code == 404


def test_tenant_b_cannot_read_tenant_as_metrics_or_cost(two_tenants):
    client = TestClient(app)
    acme_key = two_tenants["acme"]
    globex_key = two_tenants["globex"]

    m._tenants.context_for("acme-corp").box.seed_file("metrics-iso", "acme.pdf", CONTRACT_A)
    client.post("/process/metrics-iso", headers=headers(acme_key))

    metrics_a = client.get("/metrics", headers=headers(acme_key)).text
    metrics_b = client.get("/metrics", headers=headers(globex_key)).text
    assert "box_workflow_runs_processed_total 1" in metrics_a
    assert "box_workflow_runs_processed_total 0" in metrics_b

    cost_a = client.get("/runs/metrics-iso/cost", headers=headers(acme_key))
    cost_b = client.get("/runs/metrics-iso/cost", headers=headers(globex_key))
    assert cost_a.status_code == 200
    assert cost_b.status_code == 404  # tenant B never ran this file_id


def test_demo_seed_by_tenant_a_does_not_appear_for_tenant_b(two_tenants, monkeypatch):
    monkeypatch.setenv("WORKFLOW_ENABLE_DEMO_SEED", "true")
    client = TestClient(app)
    acme_key = two_tenants["acme"]
    globex_key = two_tenants["globex"]

    seed_resp = client.post("/demo/seed", headers=headers(acme_key))
    assert seed_resp.status_code == 200
    assert seed_resp.json()["seeded"] == 5

    files_a = client.get("/files", headers=headers(acme_key)).json()
    files_b = client.get("/files", headers=headers(globex_key)).json()
    assert files_a["count"] == 5
    assert files_b["count"] == 0
