import pytest
from linecard.staging import critical_change_allowed, fingerprint, map_authoritative_sections, proposal_slot, sections, staging_html

def test_heading_chunk_mapping_and_required_slots():
    mapping=map_authoritative_sections(staging_html())
    assert mapping["SPECIFICATION"]["authoritative_chunk_id"] == "LC_SPECIFICATION"

def test_duplicate_and_missing_headings_block():
    with pytest.raises(ValueError,match="duplicate"): map_authoritative_sections(staging_html()+"<h2>Specification</h2><p>x</p>")
    with pytest.raises(ValueError,match="missing"): map_authoritative_sections(staging_html().replace("<h2>Restart Check</h2><p>Replace the guard and verify the interlock before restart. Source: PDF p. 4.</p>",""))

def test_unknown_slot_and_critical_alteration_block_but_overview_is_editable():
    mapping=map_authoritative_sections(staging_html())
    with pytest.raises(ValueError): proposal_slot({"heading":"Unknown"},mapping)
    assert not critical_change_allowed("SPECIFICATION","x","Guard fastener torque: 26 N·m. Source: PDF p. 3.")[0]
    assert critical_change_allowed("TASK_OVERVIEW","x","Clear the infeed jam efficiently.")[0]

def test_all_authoritative_proposal_signals_resolve_to_one_editable_slot():
    mapping=map_authoritative_sections(staging_html(), document_id="card-durable", version=7)
    value=mapping["TASK_OVERVIEW"]
    proposal={"document_id":"card-durable", "chunk_id":value["authoritative_chunk_id"],
              "old_html_fingerprint":value["old_html_fingerprint"], "heading":"Task Overview", "base_version":7}
    assert proposal_slot(proposal,mapping) == "TASK_OVERVIEW"
    proposal["document_id"]="manual-durable"
    with pytest.raises(ValueError): proposal_slot(proposal,mapping)
