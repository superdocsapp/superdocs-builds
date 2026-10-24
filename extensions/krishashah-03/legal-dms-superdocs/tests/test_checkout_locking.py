"""
The task card's bar: "versioning, check-in and check-out ... are respected
exactly." A document locked to one lawyer must not be editable by another
until it's checked back in.
"""
import pytest

from app.dms.store import DocumentLockedError, NotCheckedOutError


def test_checkout_locks_document_to_user(dms_store):
    doc = dms_store.checkout("doc-nda-v1", "attorney-priya")
    assert doc.checked_out_by == "attorney-priya"


def test_second_user_cannot_checkout_locked_document(dms_store):
    dms_store.checkout("doc-nda-v1", "attorney-priya")
    with pytest.raises(DocumentLockedError):
        dms_store.checkout("doc-nda-v1", "attorney-sam")


def test_same_user_can_recheckout_their_own_document(dms_store):
    dms_store.checkout("doc-nda-v1", "attorney-priya")
    # Re-checking-out (e.g. reopening the file) by the SAME user is fine -
    # it's a no-op re-affirmation of the lock, not a conflict.
    doc = dms_store.checkout("doc-nda-v1", "attorney-priya")
    assert doc.checked_out_by == "attorney-priya"


def test_checkin_releases_the_lock(dms_store):
    dms_store.checkout("doc-nda-v1", "attorney-priya")
    dms_store.checkin(
        "doc-nda-v1",
        "attorney-priya",
        new_html="<p>updated</p>",
        version_comment="test checkin",
        metadata={},
    )
    doc = dms_store.get_document("doc-nda-v1", "attorney-sam")
    assert doc.checked_out_by is None


def test_checkin_by_non_holder_raises(dms_store):
    dms_store.checkout("doc-nda-v1", "attorney-priya")
    with pytest.raises(NotCheckedOutError):
        dms_store.checkin(
            "doc-nda-v1",
            "attorney-sam",  # did not hold the checkout
            new_html="<p>hijack attempt</p>",
            version_comment="should fail",
            metadata={},
        )


def test_checkin_creates_new_version_without_discarding_history(dms_store):
    doc = dms_store.get_document("doc-nda-v1", "attorney-priya")
    original_version_count = len(doc.versions)
    dms_store.checkout("doc-nda-v1", "attorney-priya")
    dms_store.checkin(
        "doc-nda-v1",
        "attorney-priya",
        new_html="<p>v2 content</p>",
        version_comment="Tightened confidentiality clause",
        metadata={"reason": "client request"},
    )
    doc = dms_store.get_document("doc-nda-v1", "attorney-sam")
    assert len(doc.versions) == original_version_count + 1
    assert doc.current_version.comment == "Tightened confidentiality clause"
    # Original version 1 must still be there, untouched.
    assert doc.versions[0].version_number == 1


def test_after_second_lawyer_locked_out_can_checkout_once_released(dms_store):
    dms_store.checkout("doc-nda-v1", "attorney-priya")
    with pytest.raises(DocumentLockedError):
        dms_store.checkout("doc-nda-v1", "attorney-sam")
    dms_store.checkin(
        "doc-nda-v1", "attorney-priya", new_html="<p>x</p>", version_comment="c", metadata={}
    )
    # Now attorney-sam should be able to check it out.
    doc = dms_store.checkout("doc-nda-v1", "attorney-sam")
    assert doc.checked_out_by == "attorney-sam"
