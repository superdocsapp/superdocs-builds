"""The machine interface, held to the same rules as the human one.

The tests worth reading are the ones about what an agent cannot do. An MCP
server is driven by something that will happily call every tool it is offered,
in a loop, without reading the descriptions — so "approve is never implicit" and
"spending is never implicit" have to be properties of the code rather than
advice in a tool description.

The last test in the file is the one that keeps this honest over time: the
server must call `ReviewQueue`, not reimplement it. A second copy of the gate is
how a machine path quietly acquires different rules from the human path.
"""

from __future__ import annotations

import dataclasses
import inspect
import io
import json
from pathlib import Path

import pytest

from reconciler import mcp_server
from reconciler.config import Config
from reconciler.mcp_server import Server, serve
from reconciler.register import Register


@pytest.fixture
def workspace(tmp_path: Path, runbooks_dir: Path) -> Path:
    target = tmp_path / "runbooks"
    target.mkdir()
    for path in runbooks_dir.iterdir():
        if path.is_file():
            (target / path.name).write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    return target


@pytest.fixture
def server(tmp_path: Path, workspace: Path) -> Server:
    config = dataclasses.replace(
        Config.load(),
        register_path=tmp_path / "register.db",
        runbook_source=workspace,
        source_mode="corpus",
        superdocs_key="",
    )
    return Server(config)


def call(server: Server, tool: str, **arguments: object) -> dict:
    """One `tools/call`, with the JSON envelope unwrapped."""
    response = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool, "arguments": arguments},
        }
    )
    assert response is not None
    result = response["result"]
    text = result["content"][0]["text"]
    if result.get("isError"):
        return {"error": text}
    return json.loads(text)


# ------------------------------------------------------------- the protocol --


def test_initialize_answers_with_the_protocol_version(server: Server) -> None:
    response = server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize"})

    assert response is not None
    assert response["result"]["protocolVersion"]
    assert response["result"]["serverInfo"]["name"] == "runbook-reconciler"


def test_the_initialized_notification_gets_no_reply(server: Server) -> None:
    """A response to a notification is a protocol violation, not a nicety."""
    assert server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_all_four_tools_are_advertised(server: Server) -> None:
    response = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})

    assert response is not None
    names = {tool["name"] for tool in response["result"]["tools"]}
    assert names == {"analyze", "propose", "approve", "apply"}


def test_every_tool_declares_a_schema(server: Server) -> None:
    response = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})

    assert response is not None
    for tool in response["result"]["tools"]:
        assert tool["inputSchema"]["type"] == "object"
        assert tool["description"]


def test_an_unknown_method_is_an_error_not_a_crash(server: Server) -> None:
    response = server.handle({"jsonrpc": "2.0", "id": 7, "method": "nonsense"})

    assert response is not None
    assert response["error"]["code"] == -32601


def test_an_unknown_tool_is_reported_against_the_request_id(server: Server) -> None:
    response = server.handle(
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "delete_wiki"}}
    )

    assert response is not None
    assert response["id"] == 3
    assert response["error"]["code"] == -32602


def test_the_stdio_loop_answers_line_by_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RR_REGISTER", str(tmp_path / "register.db"))
    monkeypatch.setenv("RR_SOURCE", "corpus")
    stdin = io.StringIO(
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        + "\n"
        + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        + "\n"
    )
    stdout = io.StringIO()

    assert serve(stdin, stdout) == 0

    lines = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert [line["id"] for line in lines] == [1, 2]


def test_malformed_json_does_not_kill_the_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RR_REGISTER", str(tmp_path / "register.db"))
    monkeypatch.setenv("RR_SOURCE", "corpus")
    stdin = io.StringIO(
        "{not json at all\n"
        + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        + "\n"
    )
    stdout = io.StringIO()

    serve(stdin, stdout)

    lines = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert lines[0]["error"]["code"] == -32700
    assert lines[1]["id"] == 2, "the server stopped after one bad line"


# ------------------------------------------------------------------ analyze --


def test_analyze_finds_the_drift_and_spends_nothing(server: Server) -> None:
    result = call(server, "analyze")

    assert result["operations_spent"] == 0
    assert result["findings"], "the corpus has planted drift"
    assert result["coverage"]
    assert all(f["evidence"] for f in result["findings"])


def test_every_finding_carries_evidence_that_names_a_file_and_line(server: Server) -> None:
    """Rule 8, at the machine interface. An agent cannot check a claim it
    cannot locate."""
    for finding in call(server, "analyze")["findings"]:
        path, _, line = finding["evidence"].rpartition(":")
        assert path
        assert line.isdigit()


def test_the_document_says_field_holds_what_the_document_says(server: Server) -> None:
    """A regression test with a story. See `_finding_json`.

    The field carried `finding.detail` for one revision — the rule's own
    description of what it checks — so a threshold finding reported "the
    document says: the threshold in the alerting rule that actually pages
    someone" next to "the estate says: 1.2". Both fields well-formed, one of
    them describing nothing on any page.
    """
    findings = call(server, "analyze")["findings"]
    threshold = next(f for f in findings if f["subject"].endswith("HighLatency:threshold"))

    assert threshold["the_document_says"] == "800ms"
    assert threshold["the_estate_says"] == "1.2"
    assert threshold["the_document_says"] in threshold["excerpt"]


def test_analyze_narrowed_to_pages_reports_no_coverage(server: Server) -> None:
    result = call(server, "analyze", pages=["1008"])

    assert result["coverage"] is None


def test_an_injection_attempt_arrives_as_a_finding_not_an_instruction(server: Server) -> None:
    """Rule 3 at the interface most exposed to it.

    The corpus contains a page addressing the automation directly. It has to
    reach an agent as a subject to report, sitting in a list of findings, with
    no path by which its text becomes something the agent was told to do.
    """
    subjects = [f["subject"] for f in call(server, "analyze")["findings"]]

    assert any("instructions-to-automation" in subject for subject in subjects)


# -------------------------------------------------- nothing implicit, ever --


def test_propose_without_confirm_spends_nothing(server: Server) -> None:
    call(server, "analyze")

    result = call(server, "propose")

    assert result["operations_spent"] == 0
    assert result["would_spend"] > 0
    assert "confirm=true" in result["detail"]


def test_propose_with_confirm_and_no_key_refuses(server: Server) -> None:
    call(server, "analyze")

    result = call(server, "propose", confirm=True)

    assert "SUPERDOCS_API_KEY" in result["error"]


def test_approve_refuses_to_decide_everything_at_once(server: Server) -> None:
    """There is no approve-all, and that is the point of the whole project."""
    call(server, "analyze")

    result = call(server, "approve", decision="approved", finding_ids=[])

    assert "finding_ids is required" in result["error"]


def test_approve_records_only_the_ids_it_was_given(server: Server) -> None:
    findings = call(server, "analyze")["findings"]
    target = findings[0]["finding_id"]

    result = call(server, "approve", decision="approved", finding_ids=[target])

    assert result["decided"] == [target]
    assert result["remaining_in_queue"] == len(findings) - 1


def test_an_unknown_finding_id_is_reported_not_raised(server: Server) -> None:
    """An agent retrying a partly-applied batch names ids that are already
    decided. Failing the call would make retrying worse than not retrying."""
    call(server, "analyze")

    result = call(server, "approve", decision="rejected", finding_ids=["not-a-real-id"])

    assert result["not_in_queue"] == ["not-a-real-id"]
    assert result["decided"] == []


def test_approve_rejects_a_decision_it_does_not_understand(server: Server) -> None:
    result = call(server, "approve", decision="maybe", finding_ids=["x"])

    assert "approved" in result["error"]


def test_apply_writes_nothing_when_nothing_was_approved(server: Server) -> None:
    """Rule 1 at the machine interface."""
    call(server, "analyze")

    result = call(server, "apply")

    assert result["applied"] == []
    assert result["ok"]


def test_apply_writes_only_what_was_approved(server: Server, workspace: Path) -> None:
    from reconciler.confluence.local import LocalSource

    findings = call(server, "analyze")["findings"]
    target = next(f for f in findings if f["subject"].endswith("PaymentsApiHighLatency:threshold"))
    with Register(server.config.register_path) as register:
        register.set_proposed(target["finding_id"], "1.2s")
    call(server, "approve", decision="approved", finding_ids=[target["finding_id"]])

    result = call(server, "apply")

    assert result["applied"] == [target["finding_id"]]
    assert "1.2s" in LocalSource(workspace).read(target["page_id"]).body


def test_a_finding_with_no_proposal_escalates_rather_than_guessing(server: Server) -> None:
    findings = call(server, "analyze")["findings"]
    target = next(f for f in findings if f["editable"] and not f["proposed"])
    call(server, "approve", decision="approved", finding_ids=[target["finding_id"]])

    result = call(server, "apply")

    assert result["applied"] == []
    assert any(e["finding_id"] == target["finding_id"] for e in result["escalated"])


# ------------------------------------------------------- one gate, not two --


def test_the_server_drives_the_review_queue_rather_than_reimplementing_it() -> None:
    """The property that keeps the two paths from diverging.

    `ReviewQueue.approve` and `.reject` are the only ways a decision is
    recorded anywhere in this project. A server that called `register.decide`
    directly would pass every behavioural test above and be a second gate with
    its own rules the day the first one gains a check.
    """
    source = inspect.getsource(mcp_server)

    assert "ReviewQueue(register)" in source
    assert "register.decide" not in source


def test_no_handler_writes_to_stdout() -> None:
    """A stray print corrupts the JSON-RPC stream and is maddening to diagnose."""
    source = inspect.getsource(mcp_server.Server)

    assert "print(" not in source
