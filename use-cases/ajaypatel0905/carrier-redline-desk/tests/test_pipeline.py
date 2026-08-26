"""End-to-end pipeline tests against the scripted fake API: no key, no network.

Covers the behaviors that matter: a full run, a run killed mid-flight and
resumed without re-billing, the human gate rejecting one change without
discarding the rest, out-of-scope proposals being denied, and embedded
instructions being reported rather than obeyed."""

import json
import pathlib
import sys
import textwrap

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.errors import GraphInterrupt
from langgraph.types import Command

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from redline_desk.graph import RedlineNodes, build_graph, open_checkpointer
from redline_desk.playbook import load_playbook
from redline_desk.superdocs import SuperDocsClient
from tests.fake_api import CHUNK_CONF, CHUNK_LIABILITY, FakeSuperDocs

PLAYBOOK_YAML = textwrap.dedent(
    """
    shipper: Bluepeak Consumer Goods, Inc.
    author_tag: Redline Desk
    rules:
      - id: R-101
        name: Liability cap
        clause_keywords: ["liability"]
        required_position: Full invoice value up to $250,000.
        fallback_wording: Carrier shall be liable for cargo loss or damage in the amount of the full actual invoice value of the affected goods, up to $250,000 per shipment.
        when_missing: insert
        severity: deal_breaker
      - id: R-111
        name: Rate confidentiality
        clause_keywords: ["confidential"]
        required_position: Standard mutual confidentiality is acceptable.
        fallback_wording: The rates and terms of this Agreement are confidential.
        when_missing: ignore
        severity: preferred
      - id: R-113
        name: Safety and compliance
        clause_keywords: ["safety rating", "fmcsa"]
        required_position: Carrier maintains FMCSA authority and a Satisfactory rating.
        fallback_wording: Carrier represents that it holds valid FMCSA operating authority and a Satisfactory safety rating.
        when_missing: insert
        severity: deal_breaker
    """
)


@pytest.fixture
def env(tmp_path):
    playbook_path = tmp_path / "playbook.yaml"
    playbook_path.write_text(PLAYBOOK_YAML)
    contract = tmp_path / "contract.docx"
    contract.write_bytes(b"fake-docx-bytes")
    fake = FakeSuperDocs()
    client = SuperDocsClient("sk_test", transport=fake)
    playbook = load_playbook(playbook_path)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    return fake, client, playbook, run_dir, contract


def _initial(contract):
    return {"contract_path": str(contract), "session_id": "test-session"}


def test_full_run_auto(env):
    fake, client, playbook, run_dir, contract = env
    nodes = RedlineNodes(client, playbook, run_dir, review_mode="auto", log=lambda *_: None)
    graph = build_graph(nodes, MemorySaver())
    config = {"configurable": {"thread_id": "t1"}}
    out = graph.invoke(_initial(contract), config)

    decisions = {r["rule_id"]: r["decision"] for r in out["records"]}
    assert decisions == {"R-101": "approved", "R-111": "untouched", "R-113": "approved"}
    assert out["touched_chunk_ids"] == [CHUNK_LIABILITY]
    assert all(p["reject_all_equals_old"] and p["accept_all_equals_new"] for p in out["proofs"])
    assert "<ins" in out["redlined_html"] and "<del" in out["redlined_html"]
    assert CHUNK_CONF in out["redlined_html"]
    assert len(out["anomalies"]) == 1  # the embedded instruction was reported...
    assert (run_dir / "redlined_contract.docx").exists()
    assert (run_dir / "negotiation_summary.docx").exists()
    summary = json.loads((run_dir / "summary.json").read_text())
    assert summary["anomalies"][0]["text"].startswith("Automated review systems")
    verification = (run_dir / "VERIFICATION.md").read_text()
    assert "MISMATCH" not in verification
    ops = {e["stage"]: e["ops_charged"] for e in out["ledger"]}
    assert ops.get("rules:R-101") == 1 and ops.get("rules:R-111") == 1  # billed turns are accounted per rule


def test_interrupt_review_deny_one_keeps_rest(env):
    fake, client, playbook, run_dir, contract = env
    nodes = RedlineNodes(client, playbook, run_dir, review_mode="interactive", log=lambda *_: None)
    graph = build_graph(nodes, MemorySaver())
    config = {"configurable": {"thread_id": "t2"}}
    graph.invoke(_initial(contract), config)

    snapshot = graph.get_state(config)
    payload = [i for t in snapshot.tasks for i in t.interrupts][0].value
    assert payload["rule_id"] == "R-101"
    change_id = payload["changes"][0]["change_id"]
    graph.invoke(Command(resume={change_id: {"approved": False, "feedback": "negotiate later"}}), config)

    while (snapshot := graph.get_state(config)).next:
        interrupts = [i for t in snapshot.tasks for i in t.interrupts]
        if interrupts:  # approve the R-113 insertion
            cid = interrupts[0].value["changes"][0]["change_id"]
            graph.invoke(Command(resume={cid: {"approved": True}}), config)
        else:
            graph.invoke(None, config)

    out = graph.get_state(config).values
    decisions = {r["rule_id"]: r["decision"] for r in out["records"]}
    assert decisions == {"R-101": "denied", "R-111": "untouched", "R-113": "approved"}
    assert out["touched_chunk_ids"] == []  # denied edit leaves the clause untouched
    assert fake.approve_calls[0]["approved"] is False


def test_kill_and_resume_without_rebilling(env, tmp_path):
    fake, client, playbook, run_dir, contract = env
    config = {"configurable": {"thread_id": "t3"}}

    nodes = RedlineNodes(client, playbook, run_dir, review_mode="interactive", log=lambda *_: None)
    graph = build_graph(nodes, open_checkpointer(run_dir))
    graph.invoke(_initial(contract), config)  # parks at the review interrupt
    bills_before = len(fake.chat_async_calls)

    # simulate a process restart: fresh nodes + fresh graph over the same checkpoint db
    nodes2 = RedlineNodes(client, playbook, run_dir, review_mode="interactive", log=lambda *_: None)
    graph2 = build_graph(nodes2, open_checkpointer(run_dir))
    snapshot = graph2.get_state(config)
    payload = [i for t in snapshot.tasks for i in t.interrupts][0].value
    graph2.invoke(Command(resume={payload["changes"][0]["change_id"]: {"approved": True}}), config)
    while (snapshot := graph2.get_state(config)).next:
        interrupts = [i for t in snapshot.tasks for i in t.interrupts]
        if interrupts:
            cid = interrupts[0].value["changes"][0]["change_id"]
            graph2.invoke(Command(resume={cid: {"approved": True}}), config)
        else:
            graph2.invoke(None, config)

    out = graph2.get_state(config).values
    assert {r["rule_id"]: r["decision"] for r in out["records"]}["R-101"] == "approved"
    assert len(fake.chat_async_calls) == bills_before + 1  # only R-111's turn was billed after resume; R-101 was not re-sent


def test_out_of_scope_proposal_is_denied(env):
    fake, client, playbook, run_dir, contract = env

    original_call = fake.__call__

    def tampering(method, path, **kwargs):
        resp = original_call(method, path, **kwargs)
        if method == "GET" and path.startswith("/jobs/"):
            job = resp.json()
            for change in (job.get("metadata") or {}).get("pending_changes") or []:
                change["chunk_id"] = "ffffffff-out-of-scope"
            return type(resp)(job)
        return resp

    client_t = SuperDocsClient("sk_test", transport=tampering)
    nodes = RedlineNodes(client_t, playbook, run_dir, review_mode="auto", log=lambda *_: None)
    graph = build_graph(nodes, MemorySaver())
    out = graph.invoke(_initial(contract), {"configurable": {"thread_id": "t4"}})
    r101 = [r for r in out["records"] if r["rule_id"] == "R-101"][0]
    assert r101["verdict"] == "out_of_scope_proposal" and r101["decision"] == "denied"
    assert out["touched_chunk_ids"] == []


def test_session_busy_from_orphaned_job_is_recovered(env):
    fake, _client, playbook, run_dir, contract = env
    busy = FakeSuperDocs(busy_once=True)
    client = SuperDocsClient("sk_test", transport=busy)
    nodes = RedlineNodes(client, playbook, run_dir, review_mode="auto", log=lambda *_: None)
    out = build_graph(nodes, MemorySaver()).invoke(_initial(contract), {"configurable": {"thread_id": "t5"}})
    assert busy.cancel_calls == ["orphan-job-1"]  # the blocker was cancelled, not worked around
    assert {r["rule_id"]: r["decision"] for r in out["records"]}["R-101"] == "approved"  # and the run completed
