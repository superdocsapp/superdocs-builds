from core.rewriter import (
    propose_rewrite,
    request_is_supported,
    strengthen_structure,
)


def test_missing_metric_requires_user_input():
    proposal = propose_rewrite(
        "Automated invoice processing using Python."
    )

    assert proposal.status == "needs_metric"
    assert proposal.proposed_bullet is None
    assert proposal.questions
    assert "No metric will be invented" in proposal.reason


def test_existing_metric_allows_rewrite():
    proposal = propose_rewrite(
        "Processed 500 invoices per month using Python."
    )

    assert proposal.status == "ready"
    assert proposal.proposed_bullet is not None
    assert "500 invoices" in proposal.proposed_bullet
    assert "500 invoices" in proposal.evidence_used


def test_user_supplied_metric_is_used_exactly():
    proposal = propose_rewrite(
        "Automated invoice processing using Python.",
        supplied_metric=(
            "Reduced processing time from 3 hours to 45 minutes."
        ),
    )

    assert proposal.status == "ready"
    assert proposal.proposed_bullet is not None
    assert "3 hours" in proposal.proposed_bullet
    assert "45 minutes" in proposal.proposed_bullet

    assert "3 hours" in proposal.evidence_used
    assert "45 minutes" in proposal.evidence_used


def test_non_quantified_user_answer_is_not_accepted():
    proposal = propose_rewrite(
        "Automated invoice processing using Python.",
        supplied_metric="It became much faster.",
    )

    assert proposal.status == "needs_metric"
    assert proposal.proposed_bullet is None


def test_unsupported_leadership_claim_is_rejected():
    proposal = propose_rewrite(
        "Built Power BI dashboards for operational reporting.",
        requested_claim="Make this say I led a five-person analytics team.",
    )

    assert proposal.status == "unsupported"
    assert proposal.proposed_bullet is None
    assert "leadership claim" in proposal.reason


def test_supported_leadership_language_passes_gate():
    supported, reason = request_is_supported(
        "Led the analytics team and built Power BI dashboards.",
        "Emphasize that I led the analytics team.",
    )

    assert supported is True
    assert "supported" in reason


def test_conservative_structure_cleanup():
    result = strengthen_structure(
        "Was responsible for processing 500 invoices per month using Python."
    )

    assert result == (
        "Processed 500 invoices per month using Python."
    )


def test_rewrite_does_not_add_unknown_metric():
    proposal = propose_rewrite(
        "Processed 500 invoices per month using Python."
    )

    assert proposal.status == "ready"

    result = proposal.proposed_bullet or ""

    assert "40%" not in result
    assert "50%" not in result
    assert "$" not in result