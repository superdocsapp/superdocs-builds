from core.corrections import (
    render_correction_request,
)
from core.memo import (
    render_reconciliation_memo,
)


def sample_report():
    return {
        "scenario_id": "TEST-001",
        "findings": [
            {
                "field_name": "interest_rate",
                "status": "variance",
                "classification": "curable",
                "observations": [
                    {
                        "filename": "approval.docx",
                        "value": 6.5,
                        "raw_value": "6.500%",
                        "supporting_quote": (
                            "Approved Rate 6.500%"
                        ),
                    },
                    {
                        "filename": "closing.docx",
                        "value": 6.625,
                        "raw_value": "6.625%",
                        "supporting_quote": (
                            "Interest Rate 6.625%"
                        ),
                    },
                ],
                "applicable_rule": {
                    "rule_id": "R-002",
                    "rule_text": (
                        "Rate must match exactly."
                    ),
                    "source_document": (
                        "approval.docx"
                    ),
                    "supporting_quote": (
                        "Final rate must match."
                    ),
                },
                "explanation": (
                    "The approved rate and final "
                    "rate differ."
                ),
                "recommended_action": (
                    "Request a revised disclosure."
                ),
                "requires_human_review": True,
            },
            {
                "field_name": "title_services",
                "status": "variance",
                "classification": "tolerable",
                "observations": [],
                "applicable_rule": {
                    "rule_id": "R-005",
                    "rule_text": (
                        "Difference up to 250 permitted."
                    ),
                    "source_document": (
                        "approval.docx"
                    ),
                    "supporting_quote": (
                        "Difference up to $250."
                    ),
                },
                "explanation": (
                    "Difference is within tolerance."
                ),
                "recommended_action": None,
                "requires_human_review": False,
            },
        ],
    }


def test_memo_contains_all_findings():
    memo = render_reconciliation_memo(
        sample_report()
    )

    assert "Interest Rate" in memo
    assert "Title & Settlement Services" in memo
    assert "R-002" in memo
    assert "R-005" in memo


def test_correction_request_contains_only_curable_items():
    request = render_correction_request(
        sample_report()
    )

    assert "Interest Rate" in request
    assert "R-002" in request

    assert (
        "Title & Settlement Services"
        not in request
    )

    assert "R-005" not in request


def test_correction_request_preserves_evidence():
    request = render_correction_request(
        sample_report()
    )

    assert "6.500%" in request
    assert "6.625%" in request
    assert "Approved Rate 6.500%" in request
    assert "Interest Rate 6.625%" in request