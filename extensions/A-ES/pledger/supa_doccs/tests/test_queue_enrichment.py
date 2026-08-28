"""Tests for review-queue provenance enrichment and cost-store wiring.

Enrichment is a rendering pass over data that already exists in state —
these tests pin down that the join surfaces retries, rule text,
confidence vs threshold, and escalation reason without recomputing or
mutating stored payloads.

The cost endpoint previously failed with "Cost store not configured"
(unwired store, same B4 pattern as audit_events); these tests pin the
wired behavior through the service layer.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.pipeline.approval import ApprovalService, InMemoryApprovalStore
from src.pipeline.approval_api import (
    router as approval_router,
    set_approval_service,
    set_queue_context_provider,
)
from src.pipeline.queue_enrichment import (
    build_run_review_context,
    derive_escalation_reason,
    enrich_item_details,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _context(**overrides):
    base = {
        "confidence_threshold": 0.7,
        "playbook_id": "microfinance_v1",
        "retries": {"extract_claims": 2},
        "escalated_from_permanent_error": False,
        "confidence_by_claim": {"claim-1": 0.55},
        "verdict_by_claim": {
            "claim-1": {
                "claim_id": "claim-1",
                "verdict": "compliant",
                "confidence": 0.55,
                "needs_human_review": False,
            }
        },
        "rules_by_id": {
            "USURY-36.1": {
                "description": "APR must not exceed 36%",
                "check_description": "Check if the stated APR exceeds 36%.",
                "check_type": "structured",
            }
        },
    }
    base.update(overrides)
    return base


def _make_client():
    """FastAPI app + router with an in-memory approval store wired."""
    from src.pipeline.approval_api import set_approval_service as _sas

    app = FastAPI()
    app.include_router(approval_router)
    service = ApprovalService(InMemoryApprovalStore())
    set_approval_service(service)
    return TestClient(app), service


@pytest.fixture()
def client():
    set_approval_service(None)
    set_queue_context_provider(None)
    yield
    set_approval_service(None)
    set_queue_context_provider(None)


# ---------------------------------------------------------------------------
# Enrichment unit tests
# ---------------------------------------------------------------------------


class TestBuildRunReviewContext:
    def test_reads_confidence_threshold_and_retries_from_step_outputs(self):
        run_row = type("R", (), {"config_snapshot": {"confidence_threshold": 0.8}})()
        steps = [
            {
                "step_name": "route_to_queue",
                "output_state": {"retries": {"extract_text": 1}},
            },
            {
                "step_name": "extract_claims",
                "output_state": {
                    "claims": [{"claim_id": "c1", "confidence": 0.42}]
                },
            },
        ]
        ctx = build_run_review_context(run_row, steps, {})
        assert ctx["confidence_threshold"] == 0.8
        assert ctx["retries"] == {"extract_text": 1}
        assert ctx["confidence_by_claim"]["c1"] == 0.42


class TestDeriveEscalationReason:
    def test_permanent_error_wins(self):
        ctx = _context(escalated_from_permanent_error=True)
        assert (
            derive_escalation_reason("claim-1", ctx)
            == "permanent_error_escalation"
        )

    def test_non_compliant_verdict(self):
        ctx = _context(
            verdict_by_claim={
                "claim-1": {
                    "verdict": "non_compliant",
                    "confidence": 0.9,
                    "needs_human_review": True,
                }
            }
        )
        assert derive_escalation_reason("claim-1", ctx) == "non_compliant_verdict"

    def test_low_confidence_below_threshold(self):
        ctx = _context()  # claim-1 compliant at 0.55 < 0.7 threshold
        assert derive_escalation_reason("claim-1", ctx) == "low_confidence"

    def test_needs_human_review_flag(self):
        ctx = _context(
            confidence_by_claim={"claim-1": 0.9},
            verdict_by_claim={
                "claim-1": {
                    "verdict": "compliant",
                    "confidence": 0.9,
                    "needs_human_review": True,
                }
            },
        )
        assert (
            derive_escalation_reason("claim-1", ctx)
            == "flagged_for_human_review"
        )


class TestEnrichItemDetails:
    def test_surfaces_all_provenance_fields(self):
        payload = {
            "summary": "s",
            "details": {"claim_id": "claim-1", "rule_id": "USURY-36.1"},
            "source_citations": [],
        }
        enriched = enrich_item_details(payload, _context())
        d = enriched["details"]
        assert d["confidence"] == 0.55
        assert d["confidence_threshold"] == 0.7
        assert d["escalation_reason"] == "low_confidence"
        assert d["retries"] == {"extract_claims": 2}
        assert d["rule_description"] == "APR must not exceed 36%"
        assert d["rule_check_description"].startswith("Check if")
        assert d["playbook_id"] == "microfinance_v1"

    def test_never_overwrites_enqueue_time_values(self):
        payload = {
            "summary": "s",
            "details": {"claim_id": "claim-1", "confidence": 0.99},
            "source_citations": [],
        }
        enriched = enrich_item_details(payload, _context())
        assert enriched["details"]["confidence"] == 0.99

    def test_original_payload_not_mutated(self):
        payload = {"summary": "s", "details": {"claim_id": "claim-1"}}
        enrich_item_details(payload, _context())
        assert payload["details"] == {"claim_id": "claim-1"}


# ---------------------------------------------------------------------------
# API surface: GET queue serves enriched details when provider wired
# ---------------------------------------------------------------------------


class TestQueueEndpointEnrichment:
    def test_queue_items_carry_provenance_fields(self, client):
        c, service = _make_client()
        run_id = str(uuid.uuid4())
        service.enqueue_item(
            run_id=run_id,
            item_type="finding",
            payload={
                "summary": "Interest rate finding",
                "details": {"claim_id": "claim-1", "rule_id": "USURY-36.1"},
                "source_citations": [],
            },
        )
        set_queue_context_provider(lambda rid: _context())

        resp = c.get(f"/approval/runs/{run_id}/queue")
        assert resp.status_code == 200
        item = resp.json()["items"][0]
        d = item["payload"]["details"]
        assert d["confidence"] == 0.55
        assert d["confidence_threshold"] == 0.7
        assert d["escalation_reason"] == "low_confidence"
        assert d["rule_description"] == "APR must not exceed 36%"
        assert d["retries"] == {"extract_claims": 2}

    def test_unwired_provider_leaves_payload_untouched(self, client):
        c, service = _make_client()
        run_id = str(uuid.uuid4())
        service.enqueue_item(
            run_id=run_id,
            item_type="finding",
            payload={"summary": "s", "details": {"claim_id": "x"}, "source_citations": []},
        )
        resp = c.get(f"/approval/runs/{run_id}/queue")
        assert resp.status_code == 200
        assert resp.json()["items"][0]["payload"]["details"] == {"claim_id": "x"}


# ---------------------------------------------------------------------------
# Cost store wiring (B4-pattern gap)
# ---------------------------------------------------------------------------


class TestCostStoreWiring:
    def test_get_run_cost_works_with_wired_store(self):
        from src.pipeline.services import get_run_cost, registry

        class FakeStore:
            def get_step_costs(self, run_id):
                return [
                    {
                        "step_name": "extract_claims",
                        "step_order": 3,
                        "status": "completed",
                        "duration_ms": 1200,
                        "input_tokens": 500,
                        "output_tokens": 200,
                        "cost_usd": 0.0042,
                    }
                ]

        previous = registry.cost_store
        registry.configure(cost_store=FakeStore())
        try:
            run_id = str(uuid.uuid4())
            result = get_run_cost(run_id)
            assert result.error is None
            assert result.stages[0].stage == "extract_claims"
            assert result.total_cost_usd == pytest.approx(0.0042)
        finally:
            registry.cost_store = previous

    def test_sql_cost_store_exposes_protocol_method(self):
        from src.pipeline.stores import SQLCostStore

        store = SQLCostStore(session_factory=None)  # method presence only
        assert hasattr(store, "get_step_costs")
