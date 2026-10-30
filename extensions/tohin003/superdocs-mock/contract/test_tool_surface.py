"""L2 -- the MCP surface, checked against the pin.

This is the layer most likely to catch a real change, and the reason is structural rather
than statistical: SuperDocs serves its MCP tools and prompts **live from the backend**.
The Claude Code plugin carries only a manifest, so the tool surface can move -- a renamed
argument, a dropped tool, a reworded description an agent routes on -- with no release
anywhere and nothing for a client to pin against.

That is what `spec/mcp-tools.json` is for, and what these tests defend.

Against `--target mock` they assert the mock advertises the pinned surface faithfully.
Against `--target live` the same assertions become a drift detector, and they cost nothing:
a handshake and two list calls spend no operations.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

PIN = Path(__file__).resolve().parent.parent / "spec" / "mcp-tools.json"

pytestmark = pytest.mark.mcp


@pytest.fixture(scope="module")
def pinned() -> dict:
    return json.loads(PIN.read_text(encoding="utf-8"))


@pytest.fixture()
def tools(api) -> list[dict]:
    api.initialize()
    return (api.rpc("tools/list", {}).get("result") or {}).get("tools", [])


@pytest.fixture()
def prompts(api) -> list[dict]:
    api.initialize()
    return (api.rpc("prompts/list", {}).get("result") or {}).get("prompts", [])


def test_handshake_reports_a_protocol_and_instructions(api):
    """B-096. Agents read `instructions` on connect; dropping it changes behaviour."""
    result = api.initialize()
    assert result.get("protocolVersion"), "no protocol version negotiated"
    assert result.get("instructions"), "the handshake carries no instructions field"
    assert result.get("serverInfo", {}).get("name")


def test_tool_names_match_the_pin(tools, pinned):
    """B-095. A dropped or renamed tool is the drift that breaks agents silently."""
    live = {t["name"] for t in tools}
    expected = {t["name"] for t in pinned["tools"]}
    assert live == expected, (
        "the MCP tool surface has moved.\n"
        f"  added:   {sorted(live - expected)}\n"
        f"  removed: {sorted(expected - live)}\n"
        "Re-pin with scripts/pin_mcp_surface.py once the change is understood, and "
        "record what moved in docs/findings.md."
    )


def test_prompt_names_match_the_pin(prompts, pinned):
    live = {p["name"] for p in prompts}
    expected = {p["name"] for p in pinned["prompts"]}
    assert live == expected, f"workflow prompts moved: {live ^ expected}"


def test_the_documented_counts_still_hold(tools, prompts):
    """38 tools and 4 prompts, per docs.superdocs.app/mcp/available-tools."""
    assert len(tools) == 38, f"docs say 38 tools; the surface reports {len(tools)}"
    assert len(prompts) == 4, f"docs say 4 prompts; the surface reports {len(prompts)}"


def test_tool_input_schemas_match_the_pin(tools, pinned):
    """A renamed or retyped argument breaks callers as surely as a renamed tool.

    Compared on property names and required lists rather than byte-equality: descriptions
    are prose and are expected to be edited, but the shape a caller codes against is not.
    """
    pinned_by_name = {t["name"]: t for t in pinned["tools"]}
    drift: list[str] = []

    for tool in tools:
        reference = pinned_by_name.get(tool["name"])
        if reference is None:
            continue  # a new tool; the name test above already reports it
        live_schema = tool.get("inputSchema") or {}
        pin_schema = reference.get("inputSchema") or {}
        live_props = set((live_schema.get("properties") or {}).keys())
        pin_props = set((pin_schema.get("properties") or {}).keys())
        if live_props != pin_props:
            drift.append(
                f"{tool['name']}: properties added {sorted(live_props - pin_props)}, "
                f"removed {sorted(pin_props - live_props)}"
            )
        live_required = set(live_schema.get("required") or [])
        pin_required = set(pin_schema.get("required") or [])
        if live_required != pin_required:
            drift.append(
                f"{tool['name']}: required added {sorted(live_required - pin_required)}, "
                f"removed {sorted(pin_required - live_required)}"
            )

    assert not drift, "MCP tool input schemas have drifted:\n  " + "\n  ".join(drift)


def test_the_four_call_contract_is_present_on_the_tool_surface(tools):
    """B-098. Whatever else moves, these four have to exist for anything to work."""
    names = {t["name"] for t in tools}
    for required in ("chat", "chat_async", "approve_change", "export_document"):
        assert required in names, f"{required} is missing from the tool surface"
    # And the tool that resolves the other flavour of pause (B-035).
    assert "continue_chat" in names


def test_non_billable_tools_are_still_free(api, target):
    """B-091. `get_account_status` is what an agent calls to budget; it must not bill."""
    if target == "mock":
        api.using("mcp-journey")
    api.initialize()
    result = api.tool("get_account_status")
    assert result.get("isError") is not True, result
    if target == "live":
        assert api.budget.spent == 0, (
            "get_account_status billed an operation; the docs call it non-billable"
        )


def test_mock_does_not_impersonate_the_real_server(api, target):
    """A test double must be identifiable as one, from the handshake alone."""
    if target != "mock":
        pytest.skip("about the mock's own honesty")
    assert "sdmock" in api.initialize()["serverInfo"]["name"].lower()
