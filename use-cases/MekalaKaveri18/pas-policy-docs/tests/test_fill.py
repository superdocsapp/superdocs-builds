import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent / "_lib"))
sys.path.insert(0, str(ROOT))

from fill import fill_template
from superdocs import parse_pending_changes


def test_review_does_not_write_until_approve():
    from app import JOBS, DecisionIn, GenerateIn, review, start

    JOBS.clear()
    first = start(GenerateIn(review_mode=True, sample=True))
    assert first["status"] == "awaiting_approval"
    assert "CGL" not in first["html"]
    assert "{{coverage_schedule}}" in first["html"]
    assert len(first["changes"]) >= 2

    cid = first["changes"][0]["change_id"]
    mid = review(first["id"], DecisionIn(decisions={cid: True}))
    assert mid["status"] == "awaiting_approval"
    assert any(r["decision"] is True for r in mid["register"])
    assert any(r["decision"] is None for r in mid["register"])

    rejected = first
    for c in list(mid["changes"]):
        rejected = review(first["id"], DecisionIn(decisions={c["change_id"]: False}))
    assert rejected["status"] == "completed"
    assert rejected["html"].count("CGL") <= mid["html"].count("CGL")

    JOBS.clear()
    again = start(GenerateIn(review_mode=True, sample=True))
    for c in list(again["changes"]):
        again = review(again["id"], DecisionIn(decisions={c["change_id"]: True}))
    assert again["status"] == "completed"
    assert "CGL" in again["html"] and "BPP" in again["html"]
    assert "2026-09-01" in again["html"]


def test_sample_payload_lands_both_lines_and_date():
    payload = json.loads((ROOT / "fixtures" / "sample-policy.json").read_text(encoding="utf-8"))
    html = fill_template(payload)
    assert payload["policy_number"] in html
    assert payload["named_insured"] in html
    assert payload["endorsement_effective_date"] in html
    assert html.count(payload["endorsement_effective_date"]) >= 2
    assert "Commercial General Liability" in html
    assert "Business Personal Property" in html
    assert "CGL" in html and "BPP" in html
    clause = html.split("Insuring agreement")[-1]
    assert payload["endorsement_effective_date"] in clause
    assert "CGL" in clause and "BPP" in clause


def test_double_encoded_pending_changes_are_objects():
    inner = json.dumps([{"change_id": "ch_9", "new_html": "<p>x</p>", "operation": "edit"}])
    job = {"metadata": {"pending_changes": inner}}
    changes = parse_pending_changes(job)
    assert changes[0]["change_id"] == "ch_9"
    assert "undefined" not in json.dumps(changes)
