import copy
import hashlib
import json
from pathlib import Path

from linecard.m1 import MANUAL_SHA256, QUOTES, evidence_pack, page_map, skeleton, verify, write_artifacts

def test_page_map_and_evidence_are_deterministic():
    a = page_map(); b = page_map()
    assert len(a["pages"]) == 4 and a == b
    assert a["manual_sha256"] == "2a0bf608d483fd156e5657975eb6a19d1381bfff8719cf22208978d6e7ef7570"
    assert "Ignore previous instructions" in a["pages"][0]["text"]
    assert "24 N·m ± 2 N·m" in a["pages"][2]["text"]
    pack = evidence_pack(a)
    assert [(x["evidence_id"], x["display_page"]) for x in pack["records"]] == [("SAFE-001",1),("STEP-001",2),("STEP-002",2),("STEP-003",2),("SPEC-001",3),("RESTART-001",4)]
    assert all(x["manual_sha256"] == MANUAL_SHA256 and x["quote_sha256"] == hashlib.sha256(x["exact_quote"].encode()).hexdigest() for x in pack["records"])

def test_skeleton_is_exactly_two_pages_and_escaped():
    value = write_artifacts(); text = value["html"]
    assert text.count('class="card-page card-page-') == 2
    assert "data-protected" in text and "data-evidence-ids" in text and "data-compressible" in text
    assert verify(text)["status"] == "PASS"
    assert "example.invalid" not in text

def test_sabotage_cases_block_with_specific_evidence():
    base = write_artifacts()["html"]
    cases = {
      "wrong-value": base.replace("24 N·m ± 2 N·m", "26 N·m"),
      "missing-safety": base.replace(QUOTES["SAFE-001"][0], "Wear required PPE."),
      "wrong-page": base.replace('data-evidence-ids="SPEC-001">PDF p. 3', 'data-evidence-ids="SPEC-001">PDF p. 2'),
      "unsupported-number": base.replace("STOP if energy", "STOP after 17 seconds if energy"),
      "missing-step": base.replace(QUOTES["STEP-002"][0], ""),
      "hostile-link": base.replace("LineCard</title>", 'LineCard</title><a href="https://example.invalid">source</a>'),
    }
    for name, altered in cases.items():
        report = verify(altered)
        assert report["status"] == "BLOCKED", name
        assert any(not c["passed"] for c in report["checks"]), name

def test_three_page_postflight_blocks():
    report = verify(write_artifacts()["html"], pages=3)
    assert report["status"] == "BLOCKED"
    assert any(c["check"] == "two-page postflight" and c["evidence_ids"] == [] for c in report["checks"])

def test_exact_value_alternatives_remain_blocked():
    base = write_artifacts()["html"]
    for value in ("24 Nm", "24 N-m", "26 N·m", "22–26 N·m", "17.7 ft-lb"):
        altered = base.replace("24 N·m ± 2 N·m", value)
        assert verify(altered)["status"] == "BLOCKED"

def test_visible_citation_mapping_is_required():
    base=write_artifacts()["html"]
    for altered in (base.replace("PDF p. 3", "PDF p. 2", 1), base.replace('data-evidence-ids="SPEC-001"', 'data-evidence-ids="OTHER"'), base.replace('<span class="source-pointer"', '<span style="display:none" class="source-pointer"')):
        report=verify(altered)
        assert any(c["check_id"] == "CITATION_PAGE_POINTERS" and not c["passed"] for c in report["checks"])

def test_m0_contract_decoders_remain_distinct():
    from linecard.superdocs_client import normalize_proposals
    polling = {"metadata": {"pending_changes": [{"change_id": "c1", "document_id": "card"}]}}
    intermediate = {"type": "proposed_change_batch", "data": {"changes": [{"change_id": "c2", "document_id": "card"}]}}
    assert normalize_proposals(polling["metadata"]["pending_changes"])[0]["change_id"] == "c1"
    assert normalize_proposals(intermediate["data"])[0]["change_id"] == "c2"
