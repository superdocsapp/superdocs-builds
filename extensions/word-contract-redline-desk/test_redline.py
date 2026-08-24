from redline_engine import RedlineEngine


def test_liability_clause_detection():

    engine = RedlineEngine("data/playbook.json")

    proposals = engine.review(
        "data/sample_contract.docx"
    )

    assert len(proposals) == 1

    proposal = proposals[0]

    assert proposal["clause"] == "Limitation of Liability"
    assert proposal["status"] == "pending"
    assert "unlimited" in proposal["before"].lower()
    assert "fees paid" in proposal["after"].lower()


def test_rejected_change_is_not_applied():

    engine = RedlineEngine("data/playbook.json")

    proposals = engine.review(
        "data/sample_contract.docx"
    )

    proposals[0]["status"] = "rejected"

    output = "output/rejected.docx"

    engine.apply_approved_changes(
        "data/sample_contract.docx",
        proposals,
        output
    )

    assert output