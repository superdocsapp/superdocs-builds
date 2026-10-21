"""Control-report route tests: consolidated report + excluded/escalated list."""

from __future__ import annotations

import uuid

import pytest


def _post_intake_all_cases(client, repo_root, idempotency_key):
    contracts_dir = repo_root / "fixtures/contracts"
    rate_cards_dir = repo_root / "fixtures/rate-cards"
    files = [
        ("contracts", (f"contract_0{i}.md", (contracts_dir / name).read_bytes()))
        for i, name in enumerate(
            [
                "contract_01_northstar.md",
                "contract_02_bluewire.md",
                "contract_03_summitlink.md",
                "contract_04_ironvale.md",
                "contract_05_pelagic.md",
            ],
            start=1,
        )
    ]
    files.append(("old_rate_card", ("old.csv", (rate_cards_dir / "rate_card_old_2024Q1.csv").read_bytes())))
    files.append(("new_rate_card", ("new.csv", (rate_cards_dir / "rate_card_new_2025Q3.csv").read_bytes())))
    data = {
        "idempotency_key": idempotency_key,
        "proposed_effective_date": "2025-12-01",
        "reference_date_override": "2025-08-06",
    }
    response = client.post("/runs", files=files, data=data)
    assert response.status_code == 200
    return response.json()["run_id"]


def test_control_report_lists_all_five_fixture_cases(client, repo_root):
    run_id = _post_intake_all_cases(client, repo_root, str(uuid.uuid4()))
    response = client.get(f"/runs/{run_id}/control-report")
    assert response.status_code == 200
    body = response.json()
    assert len(body["rows"]) == 5


def test_control_report_excludes_blocked_and_requires_review_cases(client, repo_root):
    run_id = _post_intake_all_cases(client, repo_root, str(uuid.uuid4()))
    response = client.get(f"/runs/{run_id}/control-report")
    body = response.json()

    excluded_states = {row["state"] for row in body["excluded_or_escalated"]}
    assert excluded_states <= {"blocked", "requires_review", "failed"}
    # case_03 (pricing lock) and case_04 (mutual consent) are blocked;
    # case_05 (ambiguous) requires review.
    assert len(body["excluded_or_escalated"]) == 3


def test_unknown_run_id_returns_structured_404(client):
    response = client.get("/runs/does-not-exist/control-report")
    assert response.status_code == 404
    detail = response.json()["detail"]
    assert "what" in detail and "likely_cause" in detail and "next_action" in detail
