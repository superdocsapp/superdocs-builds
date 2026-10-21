import json
import pytest

from linecard.batch import execute_batch, retry_resume
from linecard.layout import LayoutBlock, LayoutBlocked, pdf_postflight, solve_two_page
from linecard.staging import normalize_document_identities, parse_document_sync, proposal_slot, sections, staging_html
from linecard.storage import Store
from linecard.worker import DurableWorker


def test_document_sync_wrapper_map_is_authoritative_and_chunk_direct():
    mapping = parse_document_sync(staging_html(), document_id="stage-123", version=7)
    assert set(mapping) == {"TASK_OVERVIEW", "SAFETY_GATE", "PROCEDURE_1", "PROCEDURE_2", "PROCEDURE_3", "SPECIFICATION", "RESTART_CHECK", "STOP_ESCALATE"}
    assert mapping["SPECIFICATION"]["authoritative_chunk_id"] == "LC_SPECIFICATION"
    proposal = {"chunk_id": "LC_SPECIFICATION", "document_id": "stage-123", "old_html": mapping["SPECIFICATION"]["old_html"], "base_version": 7}
    assert proposal_slot(proposal, mapping) == "SPECIFICATION"
    with pytest.raises(ValueError): proposal_slot({**proposal, "chunk_id": "unknown"}, mapping)
    with pytest.raises(ValueError): proposal_slot({**proposal, "document_id": "manual-9"}, mapping)
    with pytest.raises(ValueError): proposal_slot({**proposal, "base_version": 6}, mapping)


def test_document_sync_assigns_nested_provider_chunks_to_one_lc_slot():
    html = '<div data-chunk-id="root"><h2>Task Overview</h2><p data-chunk-id="block">Clear a jam on the infeed.</p></div>'
    for section in sections()[1:]:
        html += f'<div data-chunk-id="{section.slot_id.lower()}-root"><h2>{section.heading}</h2><p data-chunk-id="{section.slot_id.lower()}-block">{section.base_text}</p></div>'
    mapping = parse_document_sync(html, document_id="durable", local=sections())
    assert mapping["TASK_OVERVIEW"]["provider_chunk_ids"] == ["root", "block"]
    assert proposal_slot({"chunk_id": "block", "document_id": "durable"}, mapping) == "TASK_OVERVIEW"
    assert all(len([slot for slot, item in mapping.items() if chunk in item["provider_chunk_ids"]]) == 1 for chunk in {c for item in mapping.values() for c in item["provider_chunk_ids"]})


def test_document_identity_roster_links_local_and_durable_forms():
    forms = normalize_document_identities([{"document_id": "doc_primary", "durable_document_id": "durable-1"}])
    assert forms["doc_primary"] == {"doc_primary", "durable-1"}


def test_proposal_accepts_the_session_local_form_of_the_authoritative_document():
    mapping = parse_document_sync(staging_html(), document_id="durable-1", version=7)
    for item in mapping.values():
        item["document_id_forms"] = {"doc_primary", "durable-1"}
    specification = mapping["SPECIFICATION"]
    assert proposal_slot({"chunk_id": specification["authoritative_chunk_id"], "document_id": "doc_primary"}, mapping) == "SPECIFICATION"


def test_durable_worker_recovers_and_records_outbox():
    store = Store(); store.create_job("j", {"task": "clear"}); store.enqueue("j", "generate", {"attempt": 1})
    worker = DurableWorker(store, lambda job: {"state": "COMPLETED", "proof": "ok"})
    assert worker.run_once() == 1 and store.get_job("j")["state"] == "COMPLETED"
    assert len(store.pending_outbox()) == 1


def test_layout_impossible_case_and_postflight_gate():
    with pytest.raises(LayoutBlocked, match="PAGE_BUDGET_UNSATISFIABLE"):
        solve_two_page([LayoutBlock(str(i), "x", True, 10) for i in range(10)], lines_per_page=10)
    assert pdf_postflight(page_count=2, text="Isolate electrical and pneumatic energy before clearing a jam. 24 N·m ± 2 N·m PDF p. 3", warnings=[])["status"] == "PASS"
    assert pdf_postflight(page_count=1, text="", warnings=["fallback"])["status"] == "BLOCKED"


def test_batch_sample_budget_and_retry_resume():
    waiting = execute_batch([{"task": "a"}], lambda _: {"status": "COMPLETED"})
    assert waiting["status"] == "AWAITING_SAMPLE"
    result = execute_batch([{"task": "a"}, {"task": "b"}], lambda task: {"status": "BLOCKED" if task["task"] == "b" else "COMPLETED"}, approve_sample=True)
    assert result["status"] == "PARTIAL_OR_BLOCKED" and result["cards"][0]["status"] == "COMPLETED"
    calls = []
    resumed = retry_resume({"task": "a"}, lambda task: (calls.append(1) or {"status": "COMPLETED" if len(calls) == 2 else "RETRY", "retryable": True}))
    assert resumed["status"] == "COMPLETED" and resumed["attempts"] == 2
