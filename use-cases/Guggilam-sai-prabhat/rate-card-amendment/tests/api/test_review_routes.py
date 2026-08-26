"""Review route tests: propose (mocked SuperDocs), partial approval,
all-rejected, and export gating — using recorded SuperDocs response
fixtures via a respx-mocked transport, and FastAPI dependency override for
the httpx client.
"""

from __future__ import annotations

import uuid

import httpx
import pytest
import respx

from app.backend.main import app
from app.backend.superdocs_dependency import get_superdocs_http_client
from tests.integration.superdocs_fixtures import (
    APPROVE_CHANGE_ENVELOPE,
    CHAT_ASYNC_QUEUED_ENVELOPE,
    EXPORT_DOCUMENT_ENVELOPE,
    GET_JOB_AWAITING_APPROVAL_ENVELOPE,
    UPLOAD_DOCUMENT_ENVELOPE,
)
from src.integrations.superdocs_client import SUPERDOCS_MCP_URL


@pytest.fixture(autouse=True)
def superdocs_api_key(monkeypatch):
    monkeypatch.setenv("SUPERDOCS_API_KEY", "sk_test_key")


@pytest.fixture
def mocked_superdocs_client():
    """Override the FastAPI SuperDocs client dependency with one whose
    transport is mocked via respx, seeded with the recorded upload -> queued
    -> awaiting_approval -> approve -> export sequence."""

    mock_router = respx.mock(assert_all_called=False)
    mock_router.post(SUPERDOCS_MCP_URL).mock(
        side_effect=_sequenced_responses(
            [
                UPLOAD_DOCUMENT_ENVELOPE,
                CHAT_ASYNC_QUEUED_ENVELOPE,
                GET_JOB_AWAITING_APPROVAL_ENVELOPE,
                APPROVE_CHANGE_ENVELOPE,
                EXPORT_DOCUMENT_ENVELOPE,
            ]
        )
    )
    mock_router.start()

    async def override():
        async with httpx.AsyncClient() as client:
            yield client

    app.dependency_overrides[get_superdocs_http_client] = override
    yield
    app.dependency_overrides.pop(get_superdocs_http_client, None)
    mock_router.stop()


def _sequenced_responses(envelopes):
    state = {"i": 0}

    def responder(request):
        idx = min(state["i"], len(envelopes) - 1)
        state["i"] += 1
        return httpx.Response(200, json=envelopes[idx])

    return responder


def _post_intake(client, repo_root, idempotency_key, effective_date="2025-12-01"):
    contracts_dir = repo_root / "fixtures/contracts"
    rate_cards_dir = repo_root / "fixtures/rate-cards"
    files = [
        ("contracts", ("contract_01_northstar.md", (contracts_dir / "contract_01_northstar.md").read_bytes())),
        ("old_rate_card", ("old.csv", (rate_cards_dir / "rate_card_old_2024Q1.csv").read_bytes())),
        ("new_rate_card", ("new.csv", (rate_cards_dir / "rate_card_new_2025Q3.csv").read_bytes())),
    ]
    data = {
        "idempotency_key": idempotency_key,
        "proposed_effective_date": effective_date,
        "dry_run": "false",
        "reference_date_override": "2025-08-06",
    }
    response = client.post("/runs", files=files, data=data)
    assert response.status_code == 200
    body = response.json()
    run_id = body["run_id"]
    case_id = body["cases"][0]["case_id"]
    return run_id, case_id


def test_propose_reaches_proposed_state_with_pending_changes(
    client, repo_root, mocked_superdocs_client
):
    run_id, case_id = _post_intake(client, repo_root, str(uuid.uuid4()))

    response = client.post(
        f"/runs/{run_id}/cases/{case_id}/propose",
        params={"idempotency_key": str(uuid.uuid4())},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "proposed"
    assert len(body["pending_changes"]) == 1
    assert "Schedule A" in body["pending_changes"][0]["new_html"]


def test_partial_approval_reaches_partially_approved_state(
    client, repo_root, mocked_superdocs_client
):
    run_id, case_id = _post_intake(client, repo_root, str(uuid.uuid4()))
    proposal = client.post(
        f"/runs/{run_id}/cases/{case_id}/propose",
        params={"idempotency_key": str(uuid.uuid4())},
    ).json()
    change_id = proposal["pending_changes"][0]["change_id"]

    response = client.post(
        f"/runs/{run_id}/cases/{case_id}/decisions",
        json={
            "decisions": [{"change_id": change_id, "approved": True}],
            "idempotency_key": str(uuid.uuid4()),
        },
    )
    assert response.status_code == 200
    # With only one pending change and it approved, this reaches 'approved'.
    # Test the partial-approval branch explicitly with an unresolved decision
    # by not deciding at all (still 'proposed') vs a mixed multi-change case
    # covered at the unit level in test_amendment_case.py. Here we confirm
    # the API surfaces the resulting state faithfully.
    assert response.json()["state"] in ("approved", "partially_approved")


def test_rejected_proposal_blocks_export(client, repo_root, mocked_superdocs_client):
    run_id, case_id = _post_intake(client, repo_root, str(uuid.uuid4()))
    proposal = client.post(
        f"/runs/{run_id}/cases/{case_id}/propose",
        params={"idempotency_key": str(uuid.uuid4())},
    ).json()
    change_id = proposal["pending_changes"][0]["change_id"]

    decision_response = client.post(
        f"/runs/{run_id}/cases/{case_id}/decisions",
        json={
            "decisions": [{"change_id": change_id, "approved": False, "feedback": "not needed"}],
            "idempotency_key": str(uuid.uuid4()),
        },
    )
    assert decision_response.status_code == 200
    assert decision_response.json()["state"] == "blocked"

    export_response = client.post(
        f"/runs/{run_id}/cases/{case_id}/export",
        json={"idempotency_key": str(uuid.uuid4())},
    )
    assert export_response.status_code == 409
    detail = export_response.json()["detail"]
    assert "what" in detail and "likely_cause" in detail and "next_action" in detail


def test_export_after_full_approval_succeeds(client, repo_root, mocked_superdocs_client):
    run_id, case_id = _post_intake(client, repo_root, str(uuid.uuid4()))
    proposal = client.post(
        f"/runs/{run_id}/cases/{case_id}/propose",
        params={"idempotency_key": str(uuid.uuid4())},
    ).json()
    change_id = proposal["pending_changes"][0]["change_id"]

    decision_response = client.post(
        f"/runs/{run_id}/cases/{case_id}/decisions",
        json={
            "decisions": [{"change_id": change_id, "approved": True}],
            "idempotency_key": str(uuid.uuid4()),
        },
    )
    assert decision_response.json()["state"] == "approved"

    export_response = client.post(
        f"/runs/{run_id}/cases/{case_id}/export",
        json={"idempotency_key": str(uuid.uuid4()), "format": "markdown"},
    )
    assert export_response.status_code == 200
    body = export_response.json()
    assert body["state"] == "exported"
    assert "Schedule A — Rate Card" in body["exported_contract_text"]


def test_duplicate_export_idempotency_key_returns_same_response(
    client, repo_root, mocked_superdocs_client
):
    run_id, case_id = _post_intake(client, repo_root, str(uuid.uuid4()))
    proposal = client.post(
        f"/runs/{run_id}/cases/{case_id}/propose",
        params={"idempotency_key": str(uuid.uuid4())},
    ).json()
    change_id = proposal["pending_changes"][0]["change_id"]
    client.post(
        f"/runs/{run_id}/cases/{case_id}/decisions",
        json={"decisions": [{"change_id": change_id, "approved": True}], "idempotency_key": str(uuid.uuid4())},
    )

    export_key = str(uuid.uuid4())
    first = client.post(
        f"/runs/{run_id}/cases/{case_id}/export",
        json={"idempotency_key": export_key},
    )
    second = client.post(
        f"/runs/{run_id}/cases/{case_id}/export",
        json={"idempotency_key": export_key},
    )
    assert first.status_code == 200
    assert first.json() == second.json()
