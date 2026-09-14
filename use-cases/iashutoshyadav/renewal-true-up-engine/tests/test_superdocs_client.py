"""Runs entirely offline against FakeSuperDocsClient - no network call, no SuperDocs quota spent. This is
what makes the whole app's test suite runnable without a live key (round-wide requirement)."""

import pytest

from app.superdocs_client import FakeSuperDocsClient, RealSuperDocsClient, make_client


def test_make_client_without_key_returns_fake():
    assert isinstance(make_client(None), FakeSuperDocsClient)
    assert isinstance(make_client(""), FakeSuperDocsClient)


def test_make_client_with_key_returns_real_without_a_network_call():
    client = make_client("sk_test_dummy")
    assert isinstance(client, RealSuperDocsClient)
    client.close()


def test_real_client_rejects_empty_key():
    with pytest.raises(ValueError):
        RealSuperDocsClient("")


def test_upload_then_export_round_trips_content():
    client = FakeSuperDocsClient()
    content = b"2.1 Monthly Entitlement is 10,000 units.\n2.2 Fee is $8,000.00 per month.\n"
    client.upload_document("contract.txt", content, session_id="s1")
    assert client.export_document("s1") == content.decode()


def test_hitl_approval_flow_applies_only_the_approved_change():
    """Mirrors the real product's verified behavior (Phase 4 of the design): approving one change edits
    only the targeted text, everything else in the document stays byte-identical."""
    client = FakeSuperDocsClient()
    original = "2.1 Monthly Entitlement is 10,000 units.\n2.2 Fee is $8,000.00 per month.\n"
    client.upload_document("contract.txt", original.encode(), session_id="s1")

    job = client.seed_pending_change(
        session_id="s1",
        old_text="Monthly Entitlement is 10,000 units",
        new_text="Monthly Entitlement is 12,000 units",
    )
    assert job.status == "awaiting_approval"
    change = job.pending_changes[0]

    client.approve_change("s1", job.job_id, change.change_id, approved=True)

    result = client.export_document("s1")
    assert "12,000 units" in result
    assert "10,000 units" not in result
    assert "Fee is $8,000.00 per month." in result  # untouched section, unchanged


def test_hitl_rejection_leaves_document_unchanged():
    client = FakeSuperDocsClient()
    original = "2.1 Monthly Entitlement is 10,000 units.\n"
    client.upload_document("contract.txt", original.encode(), session_id="s1")

    job = client.seed_pending_change(session_id="s1", old_text="10,000 units", new_text="12,000 units")
    change = job.pending_changes[0]

    client.approve_change("s1", job.job_id, change.change_id, approved=False)

    assert client.export_document("s1") == original
