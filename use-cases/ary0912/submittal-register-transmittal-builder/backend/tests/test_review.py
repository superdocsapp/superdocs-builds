def test_approved_deviation_updates_register():

    findings = [
        {
            "status": "APPROVED",
            "result": "DEVIATION",
        },
        {
            "status": "APPROVED",
            "result": "MATCH",
        },
    ]

    pending = [
        finding
        for finding in findings
        if finding["status"]
        in {
            "PENDING_REVIEW",
            "CLARIFICATION_REQUESTED",
        }
    ]

    approved_deviations = [
        finding
        for finding in findings
        if (
            finding["status"] == "APPROVED"
            and finding["result"] == "DEVIATION"
        )
    ]

    assert pending == []
    assert len(approved_deviations) == 1

def test_rejecting_one_finding_does_not_reject_other():

    findings = [
        {
            "id": "finding-1",
            "status": "REJECTED",
            "result": "DEVIATION",
        },
        {
            "id": "finding-2",
            "status": "APPROVED",
            "result": "DEVIATION",
        },
    ]

    assert findings[0]["status"] == "REJECTED"
    assert findings[1]["status"] == "APPROVED"