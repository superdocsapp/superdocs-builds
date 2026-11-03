from datetime import date

from app.workflow.governance_simulator import compute_governance_outcome


def test_contract_becomes_disposition_eligible_exactly_on_the_anniversary():
    metadata = {
        "doc_class": "contract",
        "retention_category": "contracts-7yr",
        "expiration_date": "2020-01-15",
        "counterparty_name": "Acme Logistics Inc",
        "normalized": True,
    }
    outcome = compute_governance_outcome(
        "f1", metadata, legal_hold=False, retention_policy_locked=False,
        pending_review_field_names=[], today=date(2027, 1, 15),
    )
    assert outcome.retention_anchor_field == "expiration_date"
    assert outcome.disposition_eligible_on == "2027-01-15"
    assert outcome.disposition_eligible_now is True
    assert any("expiration_date" in r for r in outcome.retention_reasoning)


def test_contract_not_yet_eligible_the_day_before():
    metadata = {
        "doc_class": "contract",
        "retention_category": "contracts-7yr",
        "expiration_date": "2020-01-15",
    }
    outcome = compute_governance_outcome(
        "f2", metadata, legal_hold=False, retention_policy_locked=False,
        pending_review_field_names=[], today=date(2027, 1, 14),
    )
    assert outcome.disposition_eligible_now is False


def test_legal_hold_blocks_disposition_even_past_the_eligible_date():
    metadata = {
        "doc_class": "contract",
        "retention_category": "contracts-7yr",
        "expiration_date": "2010-01-01",  # long past eligible
    }
    outcome = compute_governance_outcome(
        "f3", metadata, legal_hold=True, retention_policy_locked=False,
        pending_review_field_names=[], today=date(2027, 1, 1),
    )
    assert outcome.disposition_blocked_by_legal_hold is True
    assert outcome.disposition_eligible_now is False  # never computed true under a hold
    assert any("hold" in r.lower() for r in outcome.retention_reasoning)


def test_missing_anchor_date_leaves_eligibility_uncomputed_not_guessed():
    metadata = {"doc_class": "contract", "retention_category": "contracts-7yr"}
    outcome = compute_governance_outcome(
        "f4", metadata, legal_hold=False, retention_policy_locked=False,
        pending_review_field_names=[], today=date(2027, 1, 1),
    )
    assert outcome.disposition_eligible_on is None
    assert outcome.disposition_eligible_now is False
    assert any("cannot be computed" in r for r in outcome.retention_reasoning)


def test_search_facets_only_include_fields_actually_present():
    metadata = {"doc_class": "invoice"}  # no counterparty, no retention_category
    outcome = compute_governance_outcome(
        "f5", metadata, legal_hold=False, retention_policy_locked=False,
        pending_review_field_names=[], today=date(2027, 1, 1),
    )
    assert outcome.search_facets == {"doc_class": "invoice"}
    assert "counterparty_name" not in outcome.search_facets


def test_pending_review_blocks_the_filing_workflow():
    metadata = {"doc_class": "contract", "normalized": True}
    outcome = compute_governance_outcome(
        "f6", metadata, legal_hold=False, retention_policy_locked=False,
        pending_review_field_names=["contract_value"], today=date(2027, 1, 1),
    )
    assert "auto-file-to-final-location" in outcome.workflows_blocked
    assert "contract-review-workflow" not in outcome.workflows_triggered


def test_contract_review_workflow_fires_when_normalized_and_nothing_pending():
    metadata = {"doc_class": "contract", "normalized": True}
    outcome = compute_governance_outcome(
        "f7", metadata, legal_hold=False, retention_policy_locked=False,
        pending_review_field_names=[], today=date(2027, 1, 1),
    )
    assert "contract-review-workflow" in outcome.workflows_triggered


def test_disposition_eligible_triggers_disposition_review_workflow():
    metadata = {
        "doc_class": "contract",
        "retention_category": "contracts-7yr",
        "expiration_date": "2015-01-01",
        "normalized": True,
    }
    outcome = compute_governance_outcome(
        "f8", metadata, legal_hold=False, retention_policy_locked=False,
        pending_review_field_names=[], today=date(2027, 1, 1),
    )
    assert "disposition-review-workflow" in outcome.workflows_triggered
