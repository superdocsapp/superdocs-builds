from scripts.m1_demo import focused_document_from_event, synchronized_html_from_event
from scripts.m1_recover import _document_sync_event
from linecard.superdocs_client import document_html, normalize_proposals, response_items


def test_sse_document_sync_parser_uses_only_explicit_provider_html():
    assert synchronized_html_from_event(None) == ""
    assert synchronized_html_from_event({"data": {"html": "<p>synced</p>"}}) == "<p>synced</p>"
    assert synchronized_html_from_event({"data": {"document_html": "<p>synced</p>"}}) == "<p>synced</p>"
    documented = {"type": "document_sync", "content": "<p data-chunk-id=\"sync\">synced</p>", "focused_document_id": "stage"}
    assert synchronized_html_from_event(documented) == "<p data-chunk-id=\"sync\">synced</p>"
    assert focused_document_from_event(documented) == "stage"


def test_sse_proposed_change_batch_double_parses_documented_content():
    payload = {"type": "proposed_change_batch", "content": '{"changes":[{"change_id":"c1","chunk_id":"sync"}]}' }
    assert normalize_proposals(payload) == [{"change_id": "c1", "chunk_id": "sync"}]


def test_recovery_reads_document_sync_from_the_polling_event_shape():
    event = {
        "data": {
            "type": "document_sync",
            "content": '<p data-chunk-id="sync">synced</p>',
            "focused_document_id": "stage",
        }
    }
    assert _document_sync_event({"metadata": {"intermediate_responses": [event]}}) == event["data"]


def test_shared_provider_payload_decoders_preserve_documented_shapes():
    assert document_html({"content": "<p>synced</p>"}) == "<p>synced</p>"
    assert response_items({"documents": [{"document_id": "stage"}]}, "documents") == [{"document_id": "stage"}]
    assert response_items([], "documents") == []
