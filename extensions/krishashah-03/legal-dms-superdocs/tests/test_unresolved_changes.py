"""
HTTP-level regression test for a third real bug found via live testing,
distinct from the two silent-stale-version bugs already fixed and documented
in tests/test_successive_versions.py.

Approving a change can come back from SuperDocs with status="awaiting_approval"
again and a NEW pending change that was never part of the original
propose_edit() response - a multi-part batch surfacing incrementally rather
than all at once. Both this project's web client (App.jsx) and Word add-in
(taskpane.js) only stop tracking the change just decided; neither reads the
review response's remaining pending changes, so the new one is silently
dropped from what the reviewer sees, and nothing stops them from checking in
believing review is complete.

checkin() now refuses (409, with the undecided changes in the response body)
regardless of what a given client noticed. See app/services/workflow.py's
UnresolvedChangesError and tests/test_workflow_with_mocked_superdocs.py for
the unit-level coverage of the same behavior.
"""
from __future__ import annotations

USER = "attorney-priya"
MATTER = "matter-acme-nda"
DOC = "doc-nda-v1"
HEADERS = {"X-User-Id": USER}


def test_checkin_over_http_refuses_with_the_undecided_change_in_the_body(
    api_client, fake_superdocs
):
    base = f"/matters/{MATTER}/documents/{DOC}"

    checkout = api_client.post(f"{base}/checkout", headers=HEADERS)
    session_id = checkout.json()["session_id"]

    edit = api_client.post(
        f"{base}/edit",
        json={"instruction": "Add a governing law clause"},
        headers=HEADERS,
    )
    change_id = edit.json()["pending_changes"][0]["change_id"]

    fake_superdocs.surface_extra_change_on_approval[session_id] = {
        "change_id": "change-surfaced-later",
        "operation": "create",
        "chunk_id": "new",
        "document_id": "doc_primary",
        "old_html": None,
        "new_html": "<p>[AI-EDIT: also add a non-disparagement clause]</p>",
        "ai_explanation": "I have also made a related change: added a non-disparagement clause",
    }

    review = api_client.post(
        f"{base}/review",
        json={
            "job_id": edit.json()["job_id"],
            "decisions": [{"change_id": change_id, "approved": True}],
        },
        headers=HEADERS,
    )
    assert review.status_code == 200
    assert len(review.json()["remaining_pending_changes"]) == 1

    checkin = api_client.post(
        f"{base}/checkin", json={"version_comment": "Added governing law clause"}, headers=HEADERS
    )
    assert checkin.status_code == 409
    detail = checkin.json()["detail"]
    assert "never approved or rejected" in detail["message"]
    assert detail["pending_changes"][0]["change_id"] == "change-surfaced-later"

    # And the refusal must not have created a version.
    versions = api_client.get(f"{base}/versions", headers=HEADERS).json()
    assert len(versions) == 1
