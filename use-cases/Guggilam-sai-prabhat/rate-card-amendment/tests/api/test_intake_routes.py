"""Intake route tests: multi-file upload, dry-run, and duplicate submission
idempotency (same idempotency_key posted twice must not re-run analysis).
"""

from __future__ import annotations

import uuid

import pytest


def _post_intake(client, repo_root, idempotency_key, dry_run=False, effective_date="2025-12-01"):
    contracts_dir = repo_root / "fixtures/contracts"
    rate_cards_dir = repo_root / "fixtures/rate-cards"

    files = [
        ("contracts", ("contract_01_northstar.md", (contracts_dir / "contract_01_northstar.md").read_bytes())),
        ("contracts", ("contract_03_summitlink.md", (contracts_dir / "contract_03_summitlink.md").read_bytes())),
        ("old_rate_card", ("old.csv", (rate_cards_dir / "rate_card_old_2024Q1.csv").read_bytes())),
        ("new_rate_card", ("new.csv", (rate_cards_dir / "rate_card_new_2025Q3.csv").read_bytes())),
    ]
    data = {
        "idempotency_key": idempotency_key,
        "proposed_effective_date": effective_date,
        "dry_run": "true" if dry_run else "false",
        "reference_date_override": "2025-08-06",
    }
    return client.post("/runs", files=files, data=data)


def test_intake_creates_run_with_one_case_per_contract(client, repo_root):
    response = _post_intake(client, repo_root, str(uuid.uuid4()))
    assert response.status_code == 200
    body = response.json()
    assert len(body["cases"]) == 2

    partner_names = {c["partner_name"] for c in body["cases"]}
    assert "Meridian Global Transit Ltd." in partner_names
    assert "Del Rio Communications S.A." in partner_names


def test_case_03_pricing_lock_is_blocked_from_intake(client, repo_root):
    response = _post_intake(client, repo_root, str(uuid.uuid4()))
    body = response.json()
    del_rio_case = next(c for c in body["cases"] if c["partner_name"] == "Del Rio Communications S.A.")
    assert del_rio_case["state"] == "blocked"
    assert "pricing lock" in del_rio_case["blocking_reason"]


def test_duplicate_submission_returns_identical_response_without_reanalysis(client, repo_root):
    key = str(uuid.uuid4())
    first = _post_intake(client, repo_root, key)
    second = _post_intake(client, repo_root, key)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()

    # Confirm it's truly the same run/cases, not independently re-analyzed.
    run_id_1 = first.json()["run_id"]
    run_id_2 = second.json()["run_id"]
    assert run_id_1 == run_id_2


def test_missing_new_rate_card_returns_structured_422(client, repo_root):
    contracts_dir = repo_root / "fixtures/contracts"
    files = [
        ("contracts", ("contract_01_northstar.md", (contracts_dir / "contract_01_northstar.md").read_bytes())),
    ]
    data = {
        "idempotency_key": str(uuid.uuid4()),
        "proposed_effective_date": "2025-12-01",
    }
    response = client.post("/runs", files=files, data=data)
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "what" in detail and "likely_cause" in detail and "next_action" in detail


def test_dry_run_flag_is_recorded_on_run(client, repo_root):
    response = _post_intake(client, repo_root, str(uuid.uuid4()), dry_run=True)
    assert response.status_code == 200
    assert response.json()["dry_run"] is True
