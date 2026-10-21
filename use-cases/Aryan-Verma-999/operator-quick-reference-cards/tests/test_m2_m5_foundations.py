import sqlite3
import pytest

from linecard.batch import batch_manifest
from linecard.flow import hero_flow, reject_unsupported_numbers
from linecard.retrieval import EvidenceIndex, map_semantic_hint
from linecard.storage import Store

def test_fts_retrieval_and_unique_semantic_mapping():
    manifest={"pages":[{"pdf_index":0,"printed_page_label":"A-1","text":"WARNING isolate electrical energy before service."},{"pdf_index":1,"printed_page_label":"A-2","text":"Tighten guard fasteners to 24 N·m ± 2 N·m."}]}
    index=EvidenceIndex(); index.add_manifest(manifest)
    assert index.safety_sweep()[0].page_index == 0
    assert index.specification_sweep()[0].page_index == 1
    mapped=map_semantic_hint({"quote":"Tighten guard fasteners to 24 N·m ± 2 N·m."},manifest)
    assert mapped["page_index"] == 1 and mapped["start"] == 0
    with pytest.raises(ValueError): map_semantic_hint({"quote":"guard"}, {"pages": manifest["pages"] + [{"pdf_index":2,"printed_page_label":"A-3","text":"guard"}]})

def test_flow_is_typed_deterministic_and_rejects_unsupported_numbers():
    flow=hero_flow(); rendered=flow.mermaid()
    assert "ISOLATED" in rendered and "yes" in rendered and "no" in rendered
    assert flow.digest() == hero_flow().digest()
    with pytest.raises(ValueError): reject_unsupported_numbers("wait 17 seconds")

def test_durable_store_revision_and_idempotency():
    store=Store(); store.create_job("j1",{"task":"x"}); job=store.get_job("j1")
    rev=store.transition("j1",job["revision"],"RUNNING",event="started")
    with pytest.raises(RuntimeError): store.transition("j1",0,"COMPLETED")
    first=store.idempotent("k",{"a":1},{"ok":True}); assert store.idempotent("k",{"a":1},{"ok":False}) == first
    with pytest.raises(ValueError): store.idempotent("k",{"a":2},{"ok":False})

def test_batch_does_not_claim_merged_success_when_one_item_blocks():
    report=batch_manifest([{"task":"a","status":"COMPLETED"},{"task":"b","status":"BLOCKED_EVIDENCE"}])
    assert report["aggregate_status"] == "PARTIAL_OR_BLOCKED" and not report["merged_allowed"]
