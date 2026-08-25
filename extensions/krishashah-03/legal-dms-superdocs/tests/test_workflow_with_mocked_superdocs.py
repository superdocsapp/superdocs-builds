"""
End-to-end exercise of the workflow (upload -> chat/async -> approve ->
export) through DocumentWorkflow, with SuperDocs fully mocked (no network,
no API key - see tests/mocks.py). This is the test that proves the
integration logic itself, independent of whether the real SuperDocs API is
reachable.

Field names and the document_html regression test below were updated after
live Postman validation against the real API on 2026-08-12 - see
app/superdocs/client.py and app/services/workflow.py docstrings for the two
real bugs this uncovered.
"""
from app.services.workflow import EditProposal, NotEditableError, UnresolvedChangesError
import pytest


def test_checkout_uploads_current_version_to_superdocs(workflow, fake_superdocs):
    doc, session_id = workflow.checkout("matter-acme-nda", "doc-nda-v1", "attorney-priya")
    assert session_id in fake_superdocs.sessions
    assert "Mutual Non-Disclosure Agreement" in fake_superdocs.sessions[session_id].html
    assert len(fake_superdocs.upload_calls) == 1


def test_checkout_wrong_matter_id_raises(workflow):
    with pytest.raises(ValueError):
        workflow.checkout("matter-stratus-msa", "doc-nda-v1", "attorney-priya")


def test_propose_edit_before_checkout_raises(workflow):
    with pytest.raises(NotEditableError):
        workflow.propose_edit("doc-nda-v1", "attorney-priya", "Tighten section 2")


def test_propose_edit_returns_pending_changes(workflow):
    workflow.checkout("matter-acme-nda", "doc-nda-v1", "attorney-priya")
    proposal = workflow.propose_edit(
        "doc-nda-v1", "attorney-priya", "Tighten the confidentiality clause in section 2"
    )
    assert isinstance(proposal, EditProposal)
    assert proposal.status == "awaiting_approval"
    assert len(proposal.pending_changes) == 1
    change = proposal.pending_changes[0]
    assert "Tighten" in change.ai_explanation
    assert change.operation == "create"


def test_every_propose_edit_call_includes_document_html(workflow, fake_superdocs):
    """
    Regression test locking in the real bug found via live Postman testing:
    chat_async() was being called with NO document_html, so the AI couldn't
    see the document and silently asked a clarifying question instead of
    proposing an edit (job still completed with status=completed, no error).
    FakeSuperDocsClient.chat_async replicates that exact failure mode when
    document_html is missing (see tests/mocks.py), so if this fix is ever
    accidentally removed from workflow.py, this test fails loudly instead of
    the bug being caught by hand in Postman again.
    """
    workflow.checkout("matter-acme-nda", "doc-nda-v1", "attorney-priya")
    workflow.propose_edit("doc-nda-v1", "attorney-priya", "Tighten the confidentiality clause")
    assert len(fake_superdocs.chat_calls) == 1
    assert fake_superdocs.chat_calls[0]["document_html_provided"] is True


def test_second_edit_in_same_checkout_sends_latest_html_not_original(workflow, fake_superdocs):
    """
    Regression test for the second, subtler bug: within one checkout, a
    SECOND edit request must send the LATEST approved content, not the
    original checkout snapshot - otherwise approving edit #1 then requesting
    edit #2 would tell SuperDocs to discard edit #1's change. Confirms the
    session-HTML cache in DocumentWorkflow is refreshed after every approval
    and read (not the original doc.current_version.html) on every
    propose_edit call.
    """
    doc, session_id = workflow.checkout("matter-acme-nda", "doc-nda-v1", "attorney-priya")
    original_html = fake_superdocs.sessions[session_id].html

    proposal_1 = workflow.propose_edit(
        "doc-nda-v1", "attorney-priya", "Tighten the confidentiality clause"
    )
    change_id_1 = proposal_1.pending_changes[0].change_id
    workflow.review_changes(
        "doc-nda-v1",
        "attorney-priya",
        proposal_1.job_id,
        decisions=[{"change_id": change_id_1, "approved": True}],
    )

    workflow.propose_edit("doc-nda-v1", "attorney-priya", "Extend the term to 3 years")
    second_call = fake_superdocs.chat_calls[-1]
    assert second_call["document_html_provided"] is True
    # The cached HTML sent on call #2 must NOT equal the original checkout
    # snapshot - it must include edit #1's approved change.
    assert fake_superdocs.sessions[session_id].html != original_html
    assert "Tighten the confidentiality clause" in fake_superdocs.sessions[session_id].html


def test_rejecting_a_change_does_not_modify_the_document(workflow, fake_superdocs):
    doc, session_id = workflow.checkout("matter-acme-nda", "doc-nda-v1", "attorney-priya")
    proposal = workflow.propose_edit("doc-nda-v1", "attorney-priya", "Add a bad clause")
    change_id = proposal.pending_changes[0].change_id

    html_before = fake_superdocs.sessions[session_id].html
    workflow.review_changes(
        "doc-nda-v1",
        "attorney-priya",
        proposal.job_id,
        decisions=[{"change_id": change_id, "approved": False, "feedback": "Not needed"}],
    )
    assert fake_superdocs.sessions[session_id].html == html_before


def test_approving_a_change_applies_it_to_the_session_document(workflow, fake_superdocs):
    doc, session_id = workflow.checkout("matter-acme-nda", "doc-nda-v1", "attorney-priya")
    proposal = workflow.propose_edit(
        "doc-nda-v1", "attorney-priya", "Tighten the confidentiality clause"
    )
    change_id = proposal.pending_changes[0].change_id

    result = workflow.review_changes(
        "doc-nda-v1",
        "attorney-priya",
        proposal.job_id,
        decisions=[{"change_id": change_id, "approved": True}],
    )
    assert result.status == "completed"
    assert "Tighten the confidentiality clause" in fake_superdocs.sessions[session_id].html


def test_full_checkin_creates_new_dms_version_with_comment_and_metadata(workflow, dms_store):
    workflow.checkout("matter-acme-nda", "doc-nda-v1", "attorney-priya")
    proposal = workflow.propose_edit(
        "doc-nda-v1", "attorney-priya", "Tighten the confidentiality clause"
    )
    change_id = proposal.pending_changes[0].change_id
    workflow.review_changes(
        "doc-nda-v1",
        "attorney-priya",
        proposal.job_id,
        decisions=[{"change_id": change_id, "approved": True}],
    )

    version = workflow.checkin(
        "doc-nda-v1",
        "attorney-priya",
        version_comment="Tightened confidentiality language per client request",
        metadata={"reviewed_by": "attorney-priya"},
    )

    doc = dms_store.get_document("doc-nda-v1", "attorney-sam")
    assert doc.checked_out_by is None  # lock released
    assert version.version_number == 2
    assert version.comment == "Tightened confidentiality language per client request"
    assert version.metadata["matter_id"] == "matter-acme-nda"
    assert version.metadata["reviewed_by"] == "attorney-priya"
    assert version.exported_bytes is not None
    assert version.exported_format == "docx"
    # The new HTML snapshot carries the approved edit forward for next time.
    assert "Tighten the confidentiality clause" in doc.current_version.html


def test_checkin_without_checkout_raises(workflow):
    with pytest.raises(NotEditableError):
        workflow.checkin("doc-msa-v1", "attorney-sam", version_comment="no checkout happened")


def test_checkin_by_someone_other_than_the_checkout_holder_raises(workflow):
    workflow.checkout("matter-stratus-msa", "doc-msa-v1", "attorney-sam")
    with pytest.raises(NotEditableError):
        workflow.checkin("doc-msa-v1", "attorney-priya", version_comment="hijack attempt")


def test_document_never_leaves_its_matter_through_the_workflow(workflow, dms_store):
    """
    Full round trip, then confirm the document is still filed under the
    SAME matter it started in - nothing about editing or checking in ever
    re-files a document elsewhere.
    """
    workflow.checkout("matter-acme-nda", "doc-nda-v1", "attorney-priya")
    proposal = workflow.propose_edit("doc-nda-v1", "attorney-priya", "Extend the term to 3 years")
    change_id = proposal.pending_changes[0].change_id
    workflow.review_changes(
        "doc-nda-v1",
        "attorney-priya",
        proposal.job_id,
        decisions=[{"change_id": change_id, "approved": True}],
    )
    workflow.checkin("doc-nda-v1", "attorney-priya", version_comment="Extended term")

    doc = dms_store.get_document("doc-nda-v1", "attorney-sam")
    assert doc.matter_id == "matter-acme-nda"


def test_checkin_survives_a_lagging_export_after_approval(workflow, fake_superdocs):
    """
    Regression test for a SECOND, independent bug found via live testing
    after the first stale-version bug was fixed: review_changes() correctly
    determines and caches the approved HTML (via the job's own document_html,
    or its retry loop), but checkin() used to throw that cache away and call
    export_document(session_id=...) again itself - a second, unretried call
    vulnerable to the exact "completed but not yet propagated" lag this
    codebase already documents elsewhere. That race let a check-in file
    correctly-newer bytes (different from the previous version - so NOT the
    first bug) that still lacked the just-approved clause, with no error.

    tests/mocks.py's stale_export_countdown replicates the lag on demand -
    the fake client otherwise updates session.html synchronously, so no
    existing test could have caught this.
    """
    doc, session_id = workflow.checkout("matter-acme-nda", "doc-nda-v1", "attorney-priya")
    proposal = workflow.propose_edit("doc-nda-v1", "attorney-priya", "Add a governing law clause")
    change_id = proposal.pending_changes[0].change_id

    fake_superdocs.stale_export_countdown[session_id] = 1

    workflow.review_changes(
        "doc-nda-v1",
        "attorney-priya",
        proposal.job_id,
        decisions=[{"change_id": change_id, "approved": True}],
    )

    version = workflow.checkin(
        "doc-nda-v1", "attorney-priya", version_comment="Added governing law clause"
    )
    assert "Add a governing law clause" in version.html


def test_checkin_refuses_when_a_change_surfaces_after_approval_and_is_never_decided(
    workflow, fake_superdocs
):
    """
    Regression test for a real behavior found live, distinct from the two
    silent-stale-version bugs already fixed: approving a change can come back
    with status="awaiting_approval" again and a NEW pending change that
    wasn't part of the original propose_edit() response - SuperDocs proposing
    a multi-part batch incrementally rather than all at once. Neither the web
    client nor the Word add-in re-render that response's remaining pending
    changes (both only stop tracking the one just decided), so a reviewer
    using either UI would never see it and could check in believing review
    was complete - losing that change with no error, on a session that
    otherwise correctly recorded an approval.

    checkin() must refuse instead of proceeding, regardless of what any given
    client noticed.
    """
    doc, session_id = workflow.checkout("matter-acme-nda", "doc-nda-v1", "attorney-priya")
    proposal = workflow.propose_edit("doc-nda-v1", "attorney-priya", "Add a governing law clause")
    change_id = proposal.pending_changes[0].change_id

    fake_superdocs.surface_extra_change_on_approval[session_id] = {
        "change_id": "change-surfaced-later",
        "operation": "create",
        "chunk_id": "new",
        "document_id": "doc_primary",
        "old_html": None,
        "new_html": "<p>[AI-EDIT: also add a non-disparagement clause]</p>",
        "ai_explanation": "I have also made a related change: added a non-disparagement clause",
    }

    review_result = workflow.review_changes(
        "doc-nda-v1",
        "attorney-priya",
        proposal.job_id,
        decisions=[{"change_id": change_id, "approved": True}],
    )
    assert review_result.status == "awaiting_approval"
    assert len(review_result.pending_changes) == 1
    assert review_result.pending_changes[0].change_id == "change-surfaced-later"

    with pytest.raises(UnresolvedChangesError) as exc_info:
        workflow.checkin("doc-nda-v1", "attorney-priya", version_comment="Added governing law clause")
    assert exc_info.value.pending_changes[0].change_id == "change-surfaced-later"


def test_checkin_succeeds_once_the_surfaced_change_is_also_decided(workflow, fake_superdocs):
    """Counterpart to the refusal test above: once the reviewer is shown and
    decides on the surfaced change too, checkin proceeds normally."""
    doc, session_id = workflow.checkout("matter-acme-nda", "doc-nda-v1", "attorney-priya")
    proposal = workflow.propose_edit("doc-nda-v1", "attorney-priya", "Add a governing law clause")
    change_id = proposal.pending_changes[0].change_id

    fake_superdocs.surface_extra_change_on_approval[session_id] = {
        "change_id": "change-surfaced-later",
        "operation": "create",
        "chunk_id": "new",
        "document_id": "doc_primary",
        "old_html": None,
        "new_html": "<p>[AI-EDIT: also add a non-disparagement clause]</p>",
        "ai_explanation": "I have also made a related change: added a non-disparagement clause",
    }

    review_result = workflow.review_changes(
        "doc-nda-v1",
        "attorney-priya",
        proposal.job_id,
        decisions=[{"change_id": change_id, "approved": True}],
    )
    surfaced_change_id = review_result.pending_changes[0].change_id

    workflow.review_changes(
        "doc-nda-v1",
        "attorney-priya",
        proposal.job_id,
        decisions=[{"change_id": surfaced_change_id, "approved": True}],
    )

    version = workflow.checkin(
        "doc-nda-v1", "attorney-priya", version_comment="Added governing law and related clause"
    )
    assert "governing law clause" in version.html
    assert "non-disparagement clause" in version.html


def test_a_just_decided_change_echoed_back_is_not_offered_for_re_approval(
    workflow, fake_superdocs
):
    """
    Regression test for a real duplicate-content bug found live: SuperDocs's
    approve response can still list the change_id that was JUST decided in
    that same call, as an eventual-consistency echo rather than a genuinely
    new proposal. review_changes() used to add everything in the response's
    pending_changes to _unresolved_changes unconditionally - including that
    echo - so the SAME change_id came back to the caller looking like it
    still needed a decision. A reviewer approving it again re-triggers the
    "create" operation, appending the same content a second time. Confirmed
    live: a "General Release" section with its heading and paragraph both
    duplicated, traced back to exactly one change_id being approved twice.

    review_changes() must filter out any change_id that was part of THIS
    call's decisions before treating the response's pending_changes as
    "still needs review" - both for what it hands back to the caller and for
    what it records in _unresolved_changes.
    """
    doc, session_id = workflow.checkout("matter-acme-nda", "doc-nda-v1", "attorney-priya")
    proposal = workflow.propose_edit("doc-nda-v1", "attorney-priya", "Add a general release clause")
    change_id = proposal.pending_changes[0].change_id

    fake_superdocs.echo_decided_change_back[session_id] = True

    result = workflow.review_changes(
        "doc-nda-v1",
        "attorney-priya",
        proposal.job_id,
        decisions=[{"change_id": change_id, "approved": True}],
    )

    # The just-decided change must NOT be handed back as still-pending...
    assert result.pending_changes == []
    # ...nor tracked internally as unresolved - checkin must be allowed.
    version = workflow.checkin(
        "doc-nda-v1", "attorney-priya", version_comment="Added general release clause"
    )
    # And the content must appear exactly once, not twice.
    assert version.html.count("Add a general release clause") == 1


def test_checkin_pops_session_from_html_cache(workflow, dms_store):
    """
    After checkin, the workflow's internal session-HTML cache should no
    longer track the finished session - the checkout is over. This is a
    white-box check of the cache introduced to fix the second-edit bug; it
    guards against the cache growing unboundedly across many checkouts.
    """
    doc, session_id = workflow.checkout("matter-acme-nda", "doc-nda-v1", "attorney-priya")
    assert session_id in workflow._session_html
    proposal = workflow.propose_edit("doc-nda-v1", "attorney-priya", "Extend the term")
    change_id = proposal.pending_changes[0].change_id
    workflow.review_changes(
        "doc-nda-v1",
        "attorney-priya",
        proposal.job_id,
        decisions=[{"change_id": change_id, "approved": True}],
    )
    workflow.checkin("doc-nda-v1", "attorney-priya", version_comment="Extended term")
    assert session_id not in workflow._session_html
