"""A machine drives the whole flow, gate included.

No terminal, no browser: plan, advance, read what is proposed, decide it change by
change, advance again, export. The approval gate is one of the tools, so approval is an
explicit operation on the record rather than something the machine path skips.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from .conftest import FAKE_KEY, ROOT, FakeServer

SPEC = str(ROOT / "jobs" / "proof-compact.yaml")


@pytest.fixture
def mcp_env(fake_server: FakeServer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    fake_server.reset()
    monkeypatch.setenv("SUPERDOCS_API_KEY", FAKE_KEY)
    monkeypatch.setenv("SUPERDOCS_BASE_URL", fake_server.base_url)
    monkeypatch.setenv("LONGHAUL_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("LONGHAUL_SPEC", SPEC)
    monkeypatch.chdir(tmp_path)
    return fake_server


def test_every_tool_is_registered() -> None:
    import asyncio

    from longhaul.mcp_server import server

    names = {t.name for t in asyncio.run(server.list_tools())}
    assert names == {
        "plan_job", "advance_run", "list_pending_changes", "decide_changes",
        "run_status", "export_run", "adjudicate_step",
    }
    for tool in asyncio.run(server.list_tools()):
        assert tool.description, f"{tool.name} has no description for the calling model"


def test_a_machine_runs_the_whole_job_including_the_gate(mcp_env, tmp_path: Path) -> None:
    from longhaul import mcp_server as m

    planned = m.plan_job(spec_path=SPEC)
    run_id = planned["run_id"]
    assert planned["steps"] == 8
    assert planned["documents"] == 3

    rejected_ids: list[str] = []
    for _ in range(20):
        state = m.advance_run(run_id=run_id, gate="deferred", spec_path=SPEC)
        if state["status"] == "completed":
            break
        assert state["status"] == "blocked", state

        pending = m.list_pending_changes(run_id=run_id)["pending"]
        assert pending, f"blocked with nothing pending: {state}"
        group = pending[0]

        # Approve everything except changes that touch wording owned by Legal.
        decisions = []
        for change in group["changes"]:
            hands_off = "Legal" in change["old_html"]
            decisions.append({
                "change_id": change["change_id"],
                "approved": not hands_off,
                "feedback": "Legal owns this wording" if hands_off else None,
            })
            if hands_off:
                rejected_ids.append(change["change_id"])
        result = m.decide_changes(
            step_index=group["step_index"], decisions=decisions, run_id=run_id
        )
        assert "error" not in result
    else:
        pytest.fail("the machine-driven loop never reached a terminal state")

    final = m.run_status(run_id=run_id)
    assert final["status"] == "completed"
    assert final["resume_point"] is None
    assert all(s["state"] in ("done", "rejected") for s in final["steps"])

    assert rejected_ids, "the corpus should have offered at least one change to refuse"
    assert not mcp_env.stats()["duplicate_turns"]

    exported = m.export_run(out_dir=str(tmp_path / "out"), fmt="markdown", run_id=run_id)
    assert len(exported["files"]) == 3
    security = next(p for p in exported["files"] if "security-incident" in p)
    text = Path(security).read_text()
    assert "The Ops Lead and Legal jointly decide disclosure." in text  # refused
    assert "Rootly" in text                                             # approved


def test_advance_is_safe_to_call_again_on_a_finished_run(mcp_env) -> None:
    from longhaul import mcp_server as m

    run_id = m.plan_job(spec_path=SPEC)["run_id"]
    first = m.advance_run(run_id=run_id, gate="policy", spec_path=SPEC)
    assert first["status"] == "completed"
    calls = mcp_env.stats()["chat_calls"]

    again = m.advance_run(run_id=run_id, gate="policy", spec_path=SPEC)
    assert again["status"] == "completed"
    assert mcp_env.stats()["chat_calls"] == calls, "a finished run issued fresh turns"
    assert again["totals"]["skipped_already_done"] == again["totals"]["steps"]
    assert again["totals"]["executed"] == 0


def test_decisions_for_changes_that_were_never_proposed_are_refused(mcp_env) -> None:
    """A caller cannot invent an approval for something the model never offered."""
    from longhaul import mcp_server as m

    run_id = m.plan_job(spec_path=SPEC)["run_id"]
    m.advance_run(run_id=run_id, gate="deferred", spec_path=SPEC)
    result = m.decide_changes(
        step_index=0,
        decisions=[{"change_id": "ch_invented_by_the_caller", "approved": True}],
        run_id=run_id,
    )
    assert "error" in result
    assert "no such proposed changes" in result["error"]


def test_status_reports_the_findings_a_hostile_document_produced(mcp_env) -> None:
    from longhaul import mcp_server as m

    run_id = m.plan_job(spec_path=SPEC)["run_id"]
    state = m.advance_run(run_id=run_id, gate="policy", spec_path=SPEC)
    assert state["findings"], "the machine surface must surface findings too"
    assert {f["where"] for f in state["findings"]} == {"security-incident"}
