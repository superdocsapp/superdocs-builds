"""
The task card's own bar: "No document ever leaves the matter it belongs to.
Search across precedents never returns a document the user is not entitled
to see." These tests are the direct check against that bar.
"""
import pytest

from app.dms.store import EthicalWallViolation
from app.services.precedent_search import search_precedents


def test_excluded_user_cannot_list_walled_matter_documents(dms_store):
    with pytest.raises(EthicalWallViolation):
        dms_store.list_documents("matter-northwind-walled", "attorney-priya")


def test_excluded_user_cannot_read_walled_document(dms_store):
    with pytest.raises(EthicalWallViolation):
        dms_store.get_document("doc-settlement-v1", "attorney-priya")


def test_included_user_can_read_walled_document(dms_store):
    doc = dms_store.get_document("doc-settlement-v1", "attorney-sam")
    assert doc.document_id == "doc-settlement-v1"


def test_open_matter_is_readable_by_anyone(dms_store):
    doc = dms_store.get_document("doc-nda-v1", "attorney-priya")
    assert doc.matter_id == "matter-acme-nda"


def test_precedent_search_never_returns_walled_document_to_excluded_user(dms_store):
    # "Settlement" and "Confidential" are words that appear in the walled
    # document. attorney-priya is NOT on that matter's ethical wall.
    hits = search_precedents(dms_store, "attorney-priya", query="confidential settlement terms")
    hit_ids = {h.document_id for h in hits}
    assert "doc-settlement-v1" not in hit_ids


def test_precedent_search_returns_walled_document_to_included_user(dms_store):
    hits = search_precedents(dms_store, "attorney-sam", query="confidential settlement terms")
    hit_ids = {h.document_id for h in hits}
    assert "doc-settlement-v1" in hit_ids


def test_precedent_search_across_open_matters_works_normally(dms_store):
    # Both the NDA and MSA mention "Confidential Information" and are open
    # to the whole firm - a search should find both regardless of which
    # matter the searching user is currently working in.
    hits = search_precedents(dms_store, "attorney-priya", query="confidential information")
    hit_ids = {h.document_id for h in hits}
    assert "doc-nda-v1" in hit_ids
    assert "doc-msa-v1" in hit_ids


def test_checkout_of_walled_document_is_blocked_via_http(api_client):
    resp = api_client.post(
        "/matters/matter-northwind-walled/documents/doc-settlement-v1/checkout",
        headers={"X-User-Id": "attorney-priya"},
    )
    assert resp.status_code == 403


def test_list_documents_walled_matter_via_http_is_403(api_client):
    resp = api_client.get(
        "/matters/matter-northwind-walled/documents",
        headers={"X-User-Id": "attorney-priya"},
    )
    assert resp.status_code == 403
