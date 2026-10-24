from app.services.precedent_search import search_precedents, summarize_hits_with_ai


def test_search_ranks_more_relevant_document_higher(dms_store):
    hits = search_precedents(dms_store, "attorney-priya", query="mutual non-disclosure agreement")
    assert hits, "expected at least one hit"
    assert hits[0].document_id == "doc-nda-v1"


def test_search_excludes_a_named_document(dms_store):
    hits = search_precedents(
        dms_store,
        "attorney-priya",
        query="confidential information",
        exclude_document_id="doc-nda-v1",
    )
    assert all(h.document_id != "doc-nda-v1" for h in hits)


def test_search_respects_limit(dms_store):
    hits = search_precedents(dms_store, "attorney-priya", query="agreement", limit=1)
    assert len(hits) <= 1


def test_empty_query_returns_no_hits(dms_store):
    assert search_precedents(dms_store, "attorney-priya", query="   ") == []


def test_ai_summary_never_sees_walled_document_content(dms_store, fake_superdocs):
    """
    The AI-summary enrichment is a convenience layer on top of already
    access-filtered hits. Confirm the walled document's content never
    reaches SuperDocs (as an attachment) even for a query that would
    otherwise match it strongly, when run as attorney-priya (excluded from
    that matter).
    """
    hits = search_precedents(dms_store, "attorney-priya", query="confidential settlement terms")
    summarize_hits_with_ai(fake_superdocs, hits, query="confidential settlement terms")

    all_attachment_text = " ".join(a["content"] for a in fake_superdocs.uploaded_attachments)
    assert "Northwind" not in all_attachment_text
    assert "Settlement Agreement" not in all_attachment_text


def test_ai_summary_does_see_accessible_precedent_content(dms_store, fake_superdocs):
    hits = search_precedents(dms_store, "attorney-priya", query="confidential information")
    summarize_hits_with_ai(fake_superdocs, hits, query="confidential information")
    assert len(fake_superdocs.uploaded_attachments) == len(hits)
    assert len(fake_superdocs.uploaded_attachments) > 0
