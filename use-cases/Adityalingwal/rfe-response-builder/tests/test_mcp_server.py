import asyncio

import pytest

import mcp_server
from rfe import ROOT


def tool_names():
    tools = asyncio.run(mcp_server.server.list_tools())
    return {tool.name for tool in tools}


def test_the_five_operations_are_exposed_as_mcp_tools():
    assert tool_names() == {
        "check_key",
        "preview_case",
        "judge_coverage",
        "draft_response",
        "decide_changes",
    }


def test_every_tool_describes_itself_and_names_its_cost():
    tools = asyncio.run(mcp_server.server.list_tools())
    by_name = {tool.name: tool for tool in tools}
    for tool in tools:
        assert tool.description and len(tool.description) > 30
    assert "billable" in by_name["draft_response"].description
    assert "Free" in by_name["preview_case"].description


def test_the_preview_tool_runs_the_same_core_offline():
    result = mcp_server.preview_case(str(ROOT / "data"))
    assert result["requests"] == 5
    buckets = {row["request_id"]: row["coverage"] for row in result["checklist"]}
    assert buckets["R5"] == "not_provided"


def test_deciding_without_a_run_names_the_missing_step(tmp_path, monkeypatch):
    import rfe

    # point at an empty folder: the real output/ may hold a live pending
    # run, and this test must never touch it
    monkeypatch.setattr(rfe, "STATE_FILE", tmp_path / "run_state.json")
    monkeypatch.setattr(rfe, "OUT", tmp_path)
    with pytest.raises(ValueError, match="run a draft first|nothing to decide"):
        mcp_server.decide_changes(approve_all=True)


def test_a_decision_must_be_explicit_never_implied(tmp_path, monkeypatch):
    import rfe

    state = tmp_path / "run_state.json"
    state.write_text('{"session_id": "s", "job_id": "j"}', encoding="utf-8")
    pending = tmp_path / "pending_changes.json"
    pending.write_text('[{"change_id": "c1"}]', encoding="utf-8")
    monkeypatch.setattr(rfe, "STATE_FILE", state)
    monkeypatch.setattr(rfe, "OUT", tmp_path)
    with pytest.raises(ValueError, match="explicit"):
        mcp_server.decide_changes()
