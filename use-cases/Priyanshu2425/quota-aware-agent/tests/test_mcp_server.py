"""The MCP surface. Keyless — `dispatch` is callable without an MCP client,
which is deliberate: a surface only testable through a protocol client is a
surface that does not get tested."""

import json

import pytest

from quota_aware_agent import mcp_server as m
from tests.fake import FakeSuperDocs

WORK = [
    {"id": "figures", "instruction": "Fix the revenue figures.", "sections": 25,
     "severity": "critical"},
    {"id": "footer", "instruction": "Tidy the footer.", "sections": 25, "severity": "low"},
]


@pytest.fixture
def fake(monkeypatch):
    f = FakeSuperDocs(remaining=2)
    from quota_aware_agent.client import SuperDocsClient
    monkeypatch.setattr(m, "_client", lambda: SuperDocsClient(f, sleep=lambda s: None))
    return f


@pytest.fixture(autouse=True)
def _ledger_in_a_temp_file(tmp_path, monkeypatch):
    """The operation ledger is deliberately persistent -- it exists because a
    process died -- so a test that used the real one would write into the
    developer's home directory and, worse, would see work a previous test run
    had "already applied". Each test gets its own."""
    monkeypatch.setattr(m, "LEDGER_PATH", str(tmp_path / "operations.jsonl"))


def test_every_declared_tool_has_a_handler():
    """A tool an agent can see but not call is worse than no tool."""
    declared = {t["name"] for t in m.TOOLS}
    assert declared == set(m._HANDLERS)


def test_every_tool_schema_is_well_formed():
    for t in m.TOOLS:
        assert t["description"].strip()
        s = t["inputSchema"]
        assert s["type"] == "object"
        for req in s.get("required", []):
            assert req in s["properties"], f"{t['name']} requires undeclared {req!r}"
        # every property is documented or typed well enough to use blind
        for name, spec in s["properties"].items():
            assert "type" in spec or "enum" in spec, f"{t['name']}.{name} has no type"


def test_check_allowance_is_free_and_authoritative(fake):
    out = m.dispatch("check_allowance", {})
    assert out["remaining_operations"] == 2
    assert out["authoritative"] is True
    assert [p for _, p in fake.calls] == ["/v1/agents/whoami"]   # nothing billable


def test_plan_work_spends_nothing_and_changes_nothing(fake):
    out = m.dispatch("plan_work", {"steps": WORK})
    assert out["will_run"] == ["figures"]
    assert out["will_defer"] == ["footer"]
    assert out["fits_completely"] is False
    assert "Sized to fit" in out["explanation"]
    # planning must not upload, edit, approve or export
    assert [p for _, p in fake.calls] == ["/v1/agents/whoami"]


def test_plan_and_run_agree_about_what_fits(fake):
    """If the MCP path planned differently from the library path, only one of
    them would be tested. They share the agent, and this pins that."""
    planned = m.dispatch("plan_work", {"steps": WORK})
    ran = m.dispatch("run_work", {
        "session_id": "s", "filename": "d.html",
        "document_html": "<h1>x</h1>", "steps": WORK,
    })
    assert ran["completed"] == planned["will_run"]
    assert ran["deferred"] == planned["will_defer"]


def test_run_work_reports_the_trade_off_in_plain_language(fake):
    out = m.dispatch("run_work", {
        "session_id": "s", "filename": "d.html",
        "document_html": "<h1>x</h1>", "steps": WORK,
    })
    assert "Left undone" in out["plain_language"]
    assert out["allowance_at_start"]["authoritative"] is True


def test_an_unknown_tool_is_refused_by_name():
    with pytest.raises(KeyError):
        m.dispatch("delete_everything", {})


def test_a_failure_is_returned_to_the_agent_not_raised_at_the_transport(monkeypatch):
    """An agent has to be able to read the error. Dropping the connection tells
    it nothing it can act on."""
    def boom():
        raise RuntimeError("SUPERDOCS_API_KEY is not set")
    monkeypatch.setattr(m, "_client", boom)

    # this is what the MCP call_tool wrapper does
    try:
        result = m.dispatch("check_allowance", {})
    except Exception as e:
        result = {"error": str(e)}
    assert "SUPERDOCS_API_KEY" in result["error"]
    assert json.dumps(result)      # and it survives serialisation


def test_the_small_sample_bound_is_reachable_from_the_surface(fake):
    fake.remaining = 500
    out = m.dispatch("run_work", {
        "session_id": "s", "filename": "d.html", "document_html": "<h1>x</h1>",
        "steps": WORK, "max_steps": 1,
    })
    assert len(out["completed"]) == 1


# -- protocol level ----------------------------------------------------------

def test_the_server_starts_and_advertises_its_tools():
    """The functions above are testable without MCP, which is deliberate — but
    a server that imports cleanly and cannot start is worse than one that fails
    loudly. The SDK's decorator API was removed in 2.x and this build was
    written against it, so `serve()` raised AttributeError on startup while
    every other test passed. This drives a real client over stdio."""
    mcp = pytest.importorskip("mcp", reason="the MCP SDK is an optional extra")
    import asyncio
    import os
    import pathlib
    import sys

    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    # The package lives under backend/, so that is what has to be on the path.
    # Pointing PYTHONPATH at the project root instead made this test pass only
    # on a machine where the package was already pip-installed -- which is every
    # machine except a stranger's fresh clone, the one case it exists to cover.
    root = str(pathlib.Path(__file__).resolve().parents[1] / "backend")

    async def drive():
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "quota_aware_agent.mcp_server"],
            # Every credential emptied, not just the key. There are two routes
            # to SuperDocs now — your own key, or the relay — and a developer
            # who has run `cp .env.example .env` would otherwise hand this
            # subprocess working relay credentials, at which point the test
            # would make a real network call and stop proving what it says it
            # proves. Emptied rather than deleted: the dotenv loader only fills
            # names that are absent, so an empty value is what pins them.
            env={**os.environ, "PYTHONPATH": root, "SUPERDOCS_API_KEY": "",
                 "RELAY_URL": "", "RELAY_KEY": ""},
        )
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                listed = await s.list_tools()
                names = {t.name for t in listed.tools}
                # every advertised tool carries a usable schema
                for t in listed.tools:
                    assert t.description.strip()
                    assert t.input_schema["type"] == "object"
                # and a call with no key comes back as a readable error,
                # not a dropped connection
                out = await s.call_tool("check_allowance", {})
                return names, out.content[0].text

    names, text = asyncio.run(drive())
    assert names == {"check_allowance", "plan_work", "run_work",
                     "resolve_operation"}
    assert "SUPERDOCS_API_KEY" in text     # the failure is legible to the agent
