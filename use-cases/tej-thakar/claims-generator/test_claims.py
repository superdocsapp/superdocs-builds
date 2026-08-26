"""
Tests for the insurance claims correspondence generator — no live API key required.
All outbound SuperDocs HTTP calls are intercepted with respx.

Run:
    pip install -r requirements.txt
    pytest test_claims.py -v
"""
from unittest.mock import patch

import pytest
import respx
from httpx import AsyncClient, Response

from main import (
    app,
    generate_letter,
    approve_letter,
    reject_letter,
    build_instruction,
    build_document_context,
    _sessions,
    GenerateRequest,
    ClaimantInfo,
    PolicyInfo,
    ClaimInfo,
    ApprovalRequest,
    RejectionRequest,
)
from config import Settings

# ─── Constants ────────────────────────────────────────────────────────────────

BASE = "https://api.superdocs.app"
LETTER_HTML = "<p>Dear Jane Doe,</p><p>Your claim CLM-001 is approved.</p>"


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clear_sessions():
    """Reset in-memory session store before and after each test."""
    _sessions.clear()
    yield
    _sessions.clear()


@pytest.fixture
def settings():
    return Settings(superdocs_api_key="sk_test", superdocs_base_url=BASE)


@pytest.fixture
def approval_request():
    return GenerateRequest(
        claimant=ClaimantInfo(
            full_name="Jane Doe",
            address="123 Main St, Mumbai",
            email="jane@test.com",
            phone="+91 9000000000",
        ),
        policy=PolicyInfo(
            policy_number="POL-001",
            coverage_limit=500_000.0,
            deductible=10_000.0,
            coverage_type="homeowner",
        ),
        claim=ClaimInfo(
            claim_number="CLM-001",
            incident_date="2026-07-15",
            incident_type="fire damage",
            claimed_amount=80_000.0,
            adjuster_estimate=75_000.0,
            adjuster_notes="Roof partially destroyed.",
        ),
        letter_type="approval",
    )


@pytest.fixture
def denial_request(approval_request):
    return approval_request.model_copy(update={"letter_type": "denial"})


# ─── Mock settings helper ─────────────────────────────────────────────────────

def mock_get_settings(settings):
    """Return a no-arg callable that returns the test settings."""
    return lambda: settings


# ─── Unit tests: pure functions ────────────────────────────────────────────────

class TestBuildInstruction:
    def test_contains_claim_number(self, approval_request):
        instr = build_instruction(approval_request)
        assert "CLM-001" in instr

    def test_contains_letter_type_keyword(self, approval_request):
        instr = build_instruction(approval_request)
        assert "CLAIM APPROVAL" in instr.upper()

    def test_denial_includes_appeal_reference(self, denial_request):
        instr = build_instruction(denial_request)
        assert "DENIAL" in instr.upper()
        assert "appeal" in instr.lower()

    def test_approval_payout_is_amount_minus_deductible(self, approval_request):
        instr = build_instruction(approval_request)
        # payout = claimed_amount - deductible = 80000 - 10000 = 70000
        assert "70,000.00" in instr

    def test_partial_approval_uses_adjuster_estimate(self):
        req = GenerateRequest(
            claimant=ClaimantInfo(full_name="Bob", address="Delhi"),
            policy=PolicyInfo(policy_number="P2", coverage_limit=100_000, deductible=5_000),
            claim=ClaimInfo(
                claim_number="C2", incident_date="2026-01-01",
                incident_type="flood", claimed_amount=60_000, adjuster_estimate=40_000,
            ),
            letter_type="partial_approval",
        )
        instr = build_instruction(req)
        # payout = adjuster_estimate - deductible = 40000 - 5000 = 35000
        assert "35,000.00" in instr

    def test_claimant_name_appears(self, approval_request):
        instr = build_instruction(approval_request)
        assert "Jane Doe" in instr

    def test_format_rules_present(self, approval_request):
        instr = build_instruction(approval_request)
        assert "FORMAT RULES" in instr


class TestBuildDocumentContext:
    def test_is_html(self, approval_request):
        html = build_document_context(approval_request)
        assert "<h1>" in html
        assert "<p>" in html

    def test_includes_claim_number(self, approval_request):
        html = build_document_context(approval_request)
        assert "CLM-001" in html

    def test_includes_adjuster_estimate(self, approval_request):
        html = build_document_context(approval_request)
        assert "75,000.00" in html

    def test_excludes_adjuster_estimate_when_absent(self, approval_request):
        req = approval_request.model_copy(
            update={"claim": approval_request.claim.model_copy(update={"adjuster_estimate": None})}
        )
        html = build_document_context(req)
        assert "Adjuster Estimate" not in html


# ─── Integration tests: generate flow (mocked) ────────────────────────────────

@pytest.mark.asyncio
async def test_generate_letter_reaches_hitl_gate(approval_request, settings):
    """
    Core HITL requirement: generate_letter pauses at awaiting_approval
    and returns status='pending_hitl' without finalising the letter.
    """
    with patch("main.asyncio.sleep"), respx.mock(assert_all_called=False) as rsps:
        rsps.post(f"{BASE}/v1/chat/async").mock(
            return_value=Response(200, json={"job_id": "j-gen-001"})
        )
        rsps.get(f"{BASE}/v1/jobs/j-gen-001").mock(
            return_value=Response(200, json={
                "status": "awaiting_approval",
                "metadata": {"pending_changes": [{"change_id": "ch-1"}, {"change_id": "ch-2"}]},
            })
        )

        async with AsyncClient(trust_env=False) as client:
            result = await generate_letter(client, approval_request, settings)

    assert result.status == "pending_hitl"
    assert result.job_id == "j-gen-001"
    assert result.session_id is not None
    assert result.letter_html is None   # letter not finalised at HITL gate
    assert result.claim_number == "CLM-001"
    assert result.letter_type == "approval"
    # Session state stored for approve/reject
    assert result.session_id in _sessions
    stored = _sessions[result.session_id]
    assert stored["job_id"] == "j-gen-001"
    assert len(stored["pending_changes"]) == 2


@pytest.mark.asyncio
async def test_generate_letter_completes_without_gate(approval_request, settings):
    """Edge case: job completes without hitting HITL gate (no awaiting_approval)."""
    with patch("main.asyncio.sleep"), respx.mock(assert_all_called=False) as rsps:
        rsps.post(f"{BASE}/v1/chat/async").mock(
            return_value=Response(200, json={"job_id": "j-gen-002"})
        )
        rsps.get(f"{BASE}/v1/jobs/j-gen-002").mock(
            return_value=Response(200, json={"status": "completed", "result": {}})
        )
        rsps.post(f"{BASE}/v1/documents/export").mock(
            return_value=Response(200, text=LETTER_HTML)
        )

        async with AsyncClient(trust_env=False) as client:
            result = await generate_letter(client, approval_request, settings)

    assert result.status == "approved"
    assert result.letter_html == LETTER_HTML
    assert result.letter_text is not None
    assert "Jane Doe" in (result.letter_text or "")


@pytest.mark.asyncio
async def test_generate_letter_continue_prompt_auto_continued(approval_request, settings):
    """continue_prompt pause is auto-continued; job then reaches HITL gate."""
    with patch("main.asyncio.sleep"), respx.mock(assert_all_called=False) as rsps:
        rsps.post(f"{BASE}/v1/chat/async").mock(
            return_value=Response(200, json={"job_id": "j-gen-003"})
        )
        rsps.get(f"{BASE}/v1/jobs/j-gen-003").mock(
            side_effect=[
                Response(200, json={
                    "status": "awaiting_approval",
                    "metadata": {"awaiting_kind": "continue_prompt"},
                }),
                Response(200, json={
                    "status": "awaiting_approval",
                    "metadata": {"pending_changes": [{"change_id": "ch-1"}]},
                }),
            ]
        )
        rsps.post(url__regex=rf"{BASE}/v1/chat/.+/continue").mock(
            return_value=Response(200, json={})
        )

        async with AsyncClient(trust_env=False) as client:
            result = await generate_letter(client, approval_request, settings)

    assert result.status == "pending_hitl"


@pytest.mark.asyncio
async def test_generate_letter_job_fails(approval_request, settings):
    """SuperDocs job fails; error is returned without raising 500."""
    with patch("main.asyncio.sleep"), respx.mock(assert_all_called=False) as rsps:
        rsps.post(f"{BASE}/v1/chat/async").mock(
            return_value=Response(200, json={"job_id": "j-gen-004"})
        )
        rsps.get(f"{BASE}/v1/jobs/j-gen-004").mock(
            return_value=Response(200, json={"status": "failed", "error": "generation_error"})
        )

        async with AsyncClient(trust_env=False) as client:
            result = await generate_letter(client, approval_request, settings)

    assert result.status == "error"
    assert "generation_error" in (result.error or "")


@pytest.mark.asyncio
async def test_generate_letter_start_request_401(approval_request, settings):
    """401 from SuperDocs → error returned (not exception)."""
    with patch("main.asyncio.sleep"), respx.mock(assert_all_called=False) as rsps:
        rsps.post(f"{BASE}/v1/chat/async").mock(
            return_value=Response(401, json={"error": "unauthorised"})
        )

        async with AsyncClient(trust_env=False) as client:
            result = await generate_letter(client, approval_request, settings)

    assert result.status == "error"
    assert result.claim_number == "CLM-001"


# ─── Integration tests: approve flow ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_approve_letter_full_flow(settings):
    """
    Approve endpoint: stored session → SuperDocs approve call →
    poll until completed → export → return approved letter.
    """
    session_id = "test-session-approve-001"
    _sessions[session_id] = {
        "job_id": "j-approve-001",
        "pending_changes": [{"change_id": "ch-A"}, {"change_id": "ch-B"}],
        "claim_number": "CLM-002",
        "letter_type": "denial",
    }

    with patch("main.get_settings", mock_get_settings(settings)), \
         patch("main.asyncio.sleep"), \
         respx.mock(assert_all_called=False) as rsps:
        rsps.post(f"{BASE}/v1/chat/{session_id}/approve").mock(
            return_value=Response(200, json={"ok": True})
        )
        rsps.get(f"{BASE}/v1/jobs/j-approve-001").mock(
            return_value=Response(200, json={"status": "completed", "result": {}})
        )
        rsps.post(f"{BASE}/v1/documents/export").mock(
            return_value=Response(200, text=LETTER_HTML)
        )

        result = await approve_letter(session_id, ApprovalRequest(approved=True))

    assert result.status == "approved"
    assert result.letter_html == LETTER_HTML
    assert result.letter_text is not None
    assert result.claim_number == "CLM-002"
    # Session cleaned up after finalisation
    assert session_id not in _sessions


@pytest.mark.asyncio
async def test_approve_letter_export_fallback(settings):
    """Export fails after approval; falls back to document_changes."""
    session_id = "test-session-approve-002"
    _sessions[session_id] = {
        "job_id": "j-approve-002",
        "pending_changes": [{"change_id": "ch-X"}],
        "claim_number": "CLM-003",
        "letter_type": "approval",
    }

    with patch("main.get_settings", mock_get_settings(settings)), \
         patch("main.asyncio.sleep"), \
         respx.mock(assert_all_called=False) as rsps:
        rsps.post(f"{BASE}/v1/chat/{session_id}/approve").mock(
            return_value=Response(200, json={"ok": True})
        )
        rsps.get(f"{BASE}/v1/jobs/j-approve-002").mock(
            return_value=Response(200, json={
                "status": "completed",
                "result": {"document_changes": {"updated_html": LETTER_HTML}},
            })
        )
        rsps.post(f"{BASE}/v1/documents/export").mock(
            return_value=Response(500, text="server error")
        )

        result = await approve_letter(session_id, ApprovalRequest(approved=True))

    assert result.status == "approved"
    assert result.letter_html == LETTER_HTML


# ─── Integration tests: reject flow ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_reject_letter(settings):
    """Reject sends approved=false per change; session is cleaned up."""
    session_id = "test-session-reject-001"
    _sessions[session_id] = {
        "job_id": "j-reject-001",
        "pending_changes": [{"change_id": "ch-R1"}, {"change_id": "ch-R2"}],
        "claim_number": "CLM-004",
        "letter_type": "partial_approval",
    }

    captured_body = {}

    def capture_reject(request, route):
        import json as _json
        captured_body.update(_json.loads(request.content))
        return Response(200, json={"ok": True})

    with patch("main.get_settings", mock_get_settings(settings)), \
         respx.mock(assert_all_called=False) as rsps:
        rsps.post(f"{BASE}/v1/chat/{session_id}/approve").mock(
            side_effect=capture_reject
        )

        result = await reject_letter(
            session_id,
            RejectionRequest(approved=False, reason="Tone is too informal"),
        )

    assert result.status == "rejected"
    assert result.claim_number == "CLM-004"
    assert session_id not in _sessions
    # Verify approved=False was sent
    assert captured_body.get("approved") is False
    # Feedback sent with each change
    for change in captured_body.get("changes", []):
        assert change.get("approved") is False
        assert "Tone is too informal" in change.get("feedback", "")


# ─── Endpoint smoke tests (no external httpx calls) ───────────────────────────

def test_health_returns_ok():
    from starlette.testclient import TestClient
    with TestClient(app) as tc:
        resp = tc.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "service": "claims-generator"}


def test_status_unknown_session_returns_404():
    from starlette.testclient import TestClient
    with TestClient(app) as tc:
        resp = tc.get("/status/nonexistent-session-xyz")
    assert resp.status_code == 404


def test_approve_unknown_session_returns_404():
    from starlette.testclient import TestClient
    with TestClient(app) as tc:
        resp = tc.post("/approve/nonexistent-session-xyz", json={"approved": True})
    assert resp.status_code == 404


def test_reject_unknown_session_returns_404():
    from starlette.testclient import TestClient
    with TestClient(app) as tc:
        resp = tc.post("/reject/nonexistent-session-xyz", json={"approved": False})
    assert resp.status_code == 404


def test_approve_endpoint_rejects_approved_false():
    """POST /approve/{session_id} with approved=false should 400 (use /reject instead)."""
    from starlette.testclient import TestClient
    _sessions["some-session"] = {
        "job_id": "j", "pending_changes": [], "claim_number": "C", "letter_type": "approval"
    }
    with TestClient(app) as tc:
        resp = tc.post("/approve/some-session", json={"approved": False})
    assert resp.status_code == 400


def test_generate_batch_rejects_empty():
    from starlette.testclient import TestClient
    with TestClient(app) as tc:
        resp = tc.post("/generate/batch", json={"requests": []})
    assert resp.status_code == 400


def test_generate_batch_rejects_oversized():
    from starlette.testclient import TestClient
    req_payload = {
        "claimant": {"full_name": "A", "address": "B"},
        "policy": {"policy_number": "P", "coverage_limit": 100000, "deductible": 1000},
        "claim": {"claim_number": "C", "incident_date": "2026-01-01",
                  "incident_type": "flood", "claimed_amount": 5000},
        "letter_type": "denial",
    }
    with TestClient(app) as tc:
        resp = tc.post("/generate/batch", json={"requests": [req_payload] * 21})
    assert resp.status_code == 400
    assert "20" in resp.json()["detail"]
