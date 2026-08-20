from __future__ import annotations

import json
import shutil
from pathlib import Path

import httpx

from spec_doc_sync.apply import apply_plan
from spec_doc_sync.diff import diff_specs, load_spec
from spec_doc_sync.planner import build_plan
from spec_doc_sync.superdocs import SuperDocsClient


ROOT = Path(__file__).resolve().parents[1]


def copied_docs(tmp_path: Path) -> Path:
    docs = tmp_path / "docs"
    shutil.copytree(ROOT / "fixtures" / "docs", docs)
    return docs


def test_rename_updates_every_exact_occurrence_and_not_substrings(tmp_path: Path) -> None:
    docs = copied_docs(tmp_path)
    plan = build_plan(ROOT / "fixtures" / "openapi-v1.yaml", ROOT / "fixtures" / "openapi-v2.yaml", docs)
    rename = [item for item in plan.proposals if item.operation == "replace_all"]
    assert sum(item.occurrences for item in rename) == 2
    for item in plan.proposals: item.decision = "approved" if item.operation == "replace_all" else "rejected"
    apply_plan(plan, docs, tmp_path / "state.json")
    content = "\n".join(path.read_text(encoding="utf-8") for path in docs.rglob("*.md"))
    assert "customer_id" not in content
    assert content.count("account_id") == 2


def test_untouched_page_is_byte_identical(tmp_path: Path) -> None:
    docs = copied_docs(tmp_path)
    untouched_before = (docs / "authentication.md").read_bytes()
    plan = build_plan(ROOT / "fixtures" / "openapi-v1.yaml", ROOT / "fixtures" / "openapi-v2.yaml", docs)
    for item in plan.proposals: item.decision = "approved" if item.operation == "replace_all" else "rejected"
    manifest = apply_plan(plan, docs, tmp_path / "state.json")
    assert (docs / "authentication.md").read_bytes() == untouched_before
    assert manifest["proof"]["authentication.md"]["byte_identical"] is True


def test_ambiguous_rename_escalates() -> None:
    previous = {"openapi":"3.1.0","components":{"schemas":{"Thing":{"properties":{"old":{"type":"string"}}}}},"paths":{}}
    current = {"openapi":"3.1.0","components":{"schemas":{"Thing":{"properties":{"new_a":{"type":"string"},"new_b":{"type":"string"}}}}},"paths":{}}
    changes = diff_specs(previous, current)
    assert len(changes) == 1
    assert changes[0].confidence < 0.7
    assert isinstance(changes[0].after, list)


def test_state_stops_own_output_from_retriggering(tmp_path: Path) -> None:
    docs = copied_docs(tmp_path); state = tmp_path / "state.json"
    first = build_plan(ROOT / "fixtures" / "openapi-v1.yaml", ROOT / "fixtures" / "openapi-v2.yaml", docs, state)
    for item in first.proposals: item.decision = "rejected"
    apply_plan(first, docs, state)
    second = build_plan(ROOT / "fixtures" / "openapi-v1.yaml", ROOT / "fixtures" / "openapi-v2.yaml", docs, state)
    assert second.proposals == []
    assert "own output cannot retrigger" in second.stop_reason


def test_preview_makes_no_network_call(tmp_path: Path, monkeypatch) -> None:
    docs = copied_docs(tmp_path)
    def forbidden(*args, **kwargs): raise AssertionError("preview attempted network access")
    monkeypatch.setattr(httpx, "Client", forbidden)
    plan = build_plan(ROOT / "fixtures" / "openapi-v1.yaml", ROOT / "fixtures" / "openapi-v2.yaml", docs)
    assert plan.preview is True and plan.proposals


def test_live_client_uses_human_gate_contract() -> None:
    requests: list[httpx.Request] = []
    polls = iter([
        {"status":"awaiting_approval","metadata":{"pending_changes":[{"change_id":"c1","old_html":"old","new_html":"new"}]}},
        {"status":"completed","result":{"document_changes":{"updated_html":"new"}}},
    ])
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/v1/chat/async": return httpx.Response(200, json={"job_id":"j1"})
        if request.url.path == "/v1/jobs/j1": return httpx.Response(200, json=next(polls))
        if request.url.path == "/v1/chat/spec-sync-fixed/approve": return httpx.Response(200, json={"ok":True})
        return httpx.Response(404)
    client = SuperDocsClient(api_key="sk_test", base_url="https://example.test", transport=httpx.MockTransport(handler))
    from spec_doc_sync.models import EditProposal
    proposal = EditProposal("p1","ch","reference.md","replace_all","customer_id","account_id",1,.99,"rename")
    path = ROOT / "fixtures" / "docs" / "reference.md"
    import uuid
    original = uuid.uuid4; uuid.uuid4 = lambda: "fixed"
    try: result = client.propose(path, proposal, lambda change: (True, ""), poll_seconds=0)
    finally: uuid.uuid4 = original
    assert result["status"] == "completed"
    approval = next(request for request in requests if request.url.path.endswith("/approve"))
    payload = json.loads(approval.content)
    assert payload == {"job_id":"j1","approved":True,"changes":[{"change_id":"c1","approved":True,"feedback":""}]}

