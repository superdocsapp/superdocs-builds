import json
import re
from pathlib import Path
from linecard.m1 import QUOTES, skeleton, verify, write_artifacts
from linecard.fallback import compose_verified_card, sidecar_manifest, verify_staging_content
from linecard.reconciliation import bounded_diff, chunk_reconciliation, html_sha256, write_run_artifact

def test_reconciliation_record_redacts_and_hashes(tmp_path):
    p = tmp_path / "run.json"
    write_run_artifact({"document_id":"11111111-1111-4111-8111-111111111111", "authorization":"Bearer " + "sanitized-test-value", "html_sha256":html_sha256("<p>x</p>")}, p)
    data=json.loads(p.read_text())
    assert data["authorization"] == "[REDACTED]"
    assert data["document_id"] == "00000000-0000-4000-8000-000000000001"
    assert len(data["html_sha256"]) == 64

def test_reconciliation_write_is_atomic_and_preserves_full_m1_schema(tmp_path):
    p = tmp_path / "run.json"
    record = {"run_fingerprint":"f"*64, "request_hash":"a"*64, "skeleton_html_sha256":"b"*64,
      "manual":{"durable_id":"00000000-0000-4000-8000-000000000000","pre_version":4,"pre_html_sha256":"c"*64,"post_version":4,"post_html_sha256":"c"*64},
      "card":{"durable_id":"00000000-0000-4000-8000-000000000001","base_version":1,"base_html_sha256":"d"*64},
      "proposal_rounds":[{"round":1,"proposals":[],"decisions":[],"prospective_html_sha256":"e"*64}],
      "authoritative":{"version":2,"html_sha256":"g"*64},"verifier":{"status":"BLOCKED","checks":[]},
      "structural_diff":{"changed_blocks":[]},"export_attempted":False}
    write_run_artifact(record, p)
    saved=json.loads(p.read_text())
    assert saved["proposal_rounds"][0]["prospective_html_sha256"] == "e"*64
    assert not list(tmp_path.glob(".*.run.json.*"))

def test_sanitized_ids_remain_distinct_and_uuid_shaped(tmp_path):
    p=tmp_path/"run.json"; write_run_artifact({"manual":"11111111-1111-4111-8111-111111111111","card":"22222222-2222-4222-8222-222222222222","change":"33333333-3333-4333-8333-333333333333"},p)
    data=json.loads(p.read_text()); assert len(set(data.values())) == 3
    assert all(len(v)==36 and v.startswith("00000000-0000-4000-8000-") for v in data.values())


def test_chunk_reconciliation_proves_direct_ownership_without_persisting_raw_ids(tmp_path):
    mapping = {"SAFE": {"provider_chunk_ids": ["provider-root", "provider-text"]}}
    result = chunk_reconciliation(mapping, [{"chunk_id": "provider-text"}])
    assert result["all_proposals_owned"] is True
    assert result["chunk_intersection_count"] == 1
    assert "provider-text" not in repr(result)

    output = tmp_path / "run.json"
    write_run_artifact({"chunk_id": "provider-text", "provider_chunk_ids": ["provider-root"]}, output)
    assert "provider-text" not in output.read_text()
    assert "[REDACTED]" in output.read_text()

def test_saved_authoritative_failure_reproduces_exact_blocking_checks():
    fixture=json.loads((Path(__file__).parent/"fixtures/m1/authoritative-failure.json").read_text())
    base=write_artifacts()["html"]
    failed=base.replace('class="card-page card-page-1"', 'class="card-page-1"').replace('data-evidence-ids="SPEC-001">PDF p. 3', 'data-evidence-ids="SPEC-001">PDF p. 2')
    report=verify(failed)
    failed_ids={c["check_id"] for c in report["checks"] if not c["passed"]}
    assert fixture["verifier"]["status"] == "BLOCKED"
    assert failed_ids == {"PROTECTED_STRUCTURE", "CITATION_PAGE_POINTERS"}
    assert fixture["authoritative"]["html_sha256"] == fixture["card"]["base_html_sha256"]

def test_stripped_metadata_uses_sidecar_without_erasing_invariants():
    base=write_artifacts()["html"]; stripped=re.sub(r'\sdata-[a-z-]+="[^"]*"', '', base)
    assert verify_staging_content(stripped)["status"] == "PASS"
    final, report=compose_verified_card(stripped)
    assert report["final_verifier"]["status"] == "PASS"
    assert sidecar_manifest()["blocks"]["SPEC-001"] == "specification"

def test_bounded_structural_diff_identifies_card_block():
    a='<section class="card-page card-page-1"><p>safe</p></section><section class="card-page card-page-2"><p>spec</p></section>'
    b=a.replace("spec", "26 N·m")
    diff=bounded_diff(a,b)
    assert diff["changed_blocks"] == ["card-page-2"]
