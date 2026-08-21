"""The MCP server: protocol shape, and where the human gate actually is."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from docsync.mcp import HANDLERS, KNOWN_PROTOCOLS, TOOLS, Server
from docsync.superdocs import Ledger, SuperDocs
from docsync.workspace import Workspace
from tests.conftest import edit_file

BUMP_ATTEMPTS = ("src/provisioning/retry.py", "MAX_ATTEMPTS = 3", "MAX_ATTEMPTS = 5")
ADR = "docs/adr/0007-retry-policy.md"


def request(server: Server, method: str, params: dict | None = None, request_id: int = 1):
    message = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        message["params"] = params
    return server.handle_line(json.dumps(message))


def call(server: Server, name: str, arguments: dict | None = None) -> dict:
    return request(server, "tools/call", {"name": name, "arguments": arguments or {}})


def text_of(response: dict) -> str:
    return response["result"]["content"][0]["text"]


@pytest.fixture
def server(repo: Path) -> Server:
    return Server(registry_path=str(repo), max_operations=20)


@pytest.fixture
def wired(repo: Path, fake, monkeypatch) -> Server:
    """A server whose SuperDocs client is the fake, freshly built per call."""

    def client(self, *, dry_run: bool = False, max_operations: int | None = None):
        http = httpx.Client(
            transport=httpx.MockTransport(fake.handler),
            base_url="https://api.superdocs.app",
        )
        return SuperDocs(
            "sk_test", ledger=Ledger(limit=max_operations or 20, dry_run=dry_run), client=http
        )

    monkeypatch.setattr(Workspace, "client", client)
    return Server(registry_path=str(repo), max_operations=20)


class TestProtocol:
    def test_initialize_echoes_a_version_it_knows(self, server):
        result = request(
            server, "initialize", {"protocolVersion": "2024-11-05", "capabilities": {}}
        )["result"]
        assert result["protocolVersion"] == "2024-11-05"
        assert result["capabilities"]["tools"] == {"listChanged": False}
        assert result["serverInfo"]["name"] == "docsync"
        assert "docsync_apply never applies anything" in result["instructions"]

    def test_an_unknown_version_gets_ours_rather_than_an_error(self, server):
        result = request(server, "initialize", {"protocolVersion": "1.0.0"})["result"]
        assert result["protocolVersion"] in KNOWN_PROTOCOLS

    def test_a_notification_gets_no_reply_at_all(self, server):
        # Not a reply with a null id — silence. Some clients treat a response
        # to a notification as fatal.
        assert server.handle_line('{"jsonrpc":"2.0","method":"notifications/initialized"}') is None
        assert server.initialized

    def test_a_request_without_an_id_is_a_notification(self, server):
        assert server.handle_line('{"jsonrpc":"2.0","method":"tools/list"}') is None

    def test_parse_error(self, server):
        response = server.handle_line("{not json")
        assert response["error"]["code"] == -32700
        assert response["id"] is None

    def test_batches_are_refused_rather_than_half_supported(self, server):
        response = server.handle_line('[{"jsonrpc":"2.0","id":1,"method":"ping"}]')
        assert response["error"]["code"] == -32600

    def test_not_jsonrpc(self, server):
        assert server.handle_line('{"id":1,"method":"ping"}')["error"]["code"] == -32600

    def test_unknown_method(self, server):
        assert request(server, "wat")["error"]["code"] == -32601

    def test_unknown_tool_is_a_protocol_error(self, server):
        assert call(server, "docsync_nope")["error"]["code"] == -32601

    def test_a_missing_required_argument_is_a_protocol_error(self, server):
        assert call(server, "docsync_approve")["error"]["code"] == -32602

    def test_ping(self, server):
        assert request(server, "ping")["result"] == {}

    def test_a_tool_failure_is_a_result_not_a_protocol_error(self, tmp_path):
        # The model is supposed to read it and adapt, which it cannot do if the
        # transport rejects the call.
        broken = Server(registry_path=str(tmp_path))
        response = call(broken, "docsync_facts")
        assert "error" not in response
        assert response["result"]["isError"] is True
        assert "no registry at" in text_of(response)


class TestToolDefinitions:
    def test_every_tool_has_a_handler_and_every_handler_a_tool(self):
        assert {t["name"] for t in TOOLS} == set(HANDLERS)

    def test_every_tool_is_well_formed(self):
        for tool in TOOLS:
            assert tool["name"].startswith("docsync_")
            assert tool["description"].strip()
            assert tool["inputSchema"]["type"] == "object"
            assert "properties" in tool["inputSchema"]

    def test_there_is_no_approve_everything_argument(self):
        # The gate is structural: approving in bulk has to be spelled out one
        # change id at a time. See the module docstring for what that does and
        # does not buy you.
        approve = next(t for t in TOOLS if t["name"] == "docsync_approve")
        assert approve["inputSchema"]["required"] == ["change_ids"]
        assert set(approve["inputSchema"]["properties"]) == {"change_ids", "write_back"}
        assert approve["annotations"]["destructiveHint"] is True

    def test_the_free_tools_are_marked_read_only(self):
        for name in ("docsync_facts", "docsync_audit", "docsync_plan", "docsync_pending"):
            tool = next(t for t in TOOLS if t["name"] == name)
            assert tool["annotations"]["readOnlyHint"] is True


class TestFreeTools:
    def test_facts(self, server):
        assert "retry.max_attempts" in text_of(call(server, "docsync_facts"))

    def test_audit(self, server):
        out = text_of(call(server, "docsync_audit"))
        assert "anchored" in out and "WEAK" in out

    def test_plan_needs_a_baseline_and_says_so(self, server):
        assert call(server, "docsync_plan")["result"]["isError"] is True

    def test_snapshot_then_plan(self, server, repo: Path):
        call(server, "docsync_snapshot")
        edit_file(repo, *BUMP_ATTEMPTS)
        out = text_of(call(server, "docsync_plan"))
        assert "Maximum retry attempts: 3  →  5" in out
        assert "billable operation" in out

    def test_plan_reads_the_repo_fresh_on_every_call(self, server, repo: Path):
        # The files change underneath this tool constantly; a cached workspace
        # would answer questions about the repo as it was when the editor
        # started.
        call(server, "docsync_snapshot")
        assert "No tracked fact moved" in text_of(call(server, "docsync_plan"))
        edit_file(repo, *BUMP_ATTEMPTS)
        assert "1 fact(s) moved" in text_of(call(server, "docsync_plan"))


class TestGate:
    def test_apply_stages_and_applies_nothing(self, wired, repo: Path, fake):
        call(wired, "docsync_snapshot")
        edit_file(repo, *BUMP_ATTEMPTS)
        out = text_of(call(wired, "docsync_apply"))

        assert "STAGED — nothing has been applied" in out
        assert "up to 3 times" in fake.body_of(fake.find_document("0007-retry-policy"))
        assert not fake.approvals
        assert (repo / ADR).read_text().count("up to 3 times") == 1

    def test_approve_applies_only_the_named_ids(self, wired, repo: Path, fake):
        call(wired, "docsync_snapshot")
        edit_file(repo, *BUMP_ATTEMPTS)
        call(wired, "docsync_apply")
        pending = json.loads((repo / ".docsync" / "pending.json").read_text())
        change_id = pending["jobs"][0]["changes"][0]["change_id"]

        out = text_of(call(wired, "docsync_approve", {"change_ids": [change_id]}))
        assert "1 approved" in out
        assert "up to 5 times" in fake.body_of(fake.find_document("0007-retry-policy"))
        assert "up to 5 times" in (repo / ADR).read_text()

    def test_approve_rejects_everything_not_named(self, wired, repo: Path, fake):
        call(wired, "docsync_snapshot")
        edit_file(repo, *BUMP_ATTEMPTS)
        call(wired, "docsync_apply")
        out = text_of(call(wired, "docsync_approve", {"change_ids": []}))
        assert "0 approved" in out
        assert "up to 3 times" in fake.body_of(fake.find_document("0007-retry-policy"))

    def test_an_unknown_change_id_is_refused_and_lists_the_real_ones(
        self, wired, repo: Path
    ):
        call(wired, "docsync_snapshot")
        edit_file(repo, *BUMP_ATTEMPTS)
        call(wired, "docsync_apply")
        response = call(wired, "docsync_approve", {"change_ids": ["made-up"]})
        assert response["result"]["isError"] is True
        assert "not in the staged batch" in text_of(response)

    def test_approve_with_nothing_staged(self, wired):
        response = call(wired, "docsync_approve", {"change_ids": []})
        assert response["result"]["isError"] is True
        assert "nothing is staged" in text_of(response)

    def test_staging_twice_is_refused_rather_than_losing_the_first_batch(
        self, wired, repo: Path
    ):
        call(wired, "docsync_snapshot")
        edit_file(repo, *BUMP_ATTEMPTS)
        call(wired, "docsync_apply")
        response = call(wired, "docsync_apply")
        assert response["result"]["isError"] is True
        assert "already staged" in text_of(response)

    def test_discard_rejects_everything_and_touches_no_document(
        self, wired, repo: Path, fake
    ):
        call(wired, "docsync_snapshot")
        edit_file(repo, *BUMP_ATTEMPTS)
        call(wired, "docsync_apply")
        out = text_of(call(wired, "docsync_discard"))
        assert "Rejected and discarded 1" in out
        assert "up to 3 times" in fake.body_of(fake.find_document("0007-retry-policy"))
        assert not (repo / ".docsync" / "pending.json").exists()

    def test_cli_only_mode_makes_the_gate_enforceable(
        self, wired, repo: Path, monkeypatch
    ):
        # The honest fallback: an agent holding both tools can call approve
        # itself. This is the setting that takes that away.
        monkeypatch.setenv("DOCSYNC_APPROVE_MODE", "cli")
        call(wired, "docsync_snapshot")
        edit_file(repo, *BUMP_ATTEMPTS)
        call(wired, "docsync_apply")
        response = call(wired, "docsync_approve", {"change_ids": ["anything"]})
        assert response["result"]["isError"] is True
        assert "restricted to the command line" in text_of(response)

    def test_a_blocked_plan_sends_nothing(self, wired, repo: Path, fake):
        call(wired, "docsync_snapshot")
        edit_file(repo, "src/provisioning/retry.py", "MAX_ATTEMPTS = 3", "MAX_ATTEMPTS = f()")
        response = call(wired, "docsync_apply")
        assert response["result"]["isError"] is True
        assert "Refusing to send anything" in text_of(response)
        assert fake.documents == {}

    def test_a_plan_over_budget_sends_nothing(self, wired, repo: Path, fake):
        call(wired, "docsync_snapshot")
        edit_file(repo, *BUMP_ATTEMPTS)
        response = call(wired, "docsync_apply", {"max_operations": 1})
        assert response["result"]["isError"] is True
        assert "budget is 1" in text_of(response)
        assert fake.documents == {}


class TestSubprocess:
    def test_a_real_stdio_session(self, repo: Path):
        """Driven the way an editor drives it: a subprocess, over pipes."""
        messages = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                        "clientInfo": {"name": "t", "version": "0"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
             "params": {"name": "docsync_facts", "arguments": {}}},
        ]
        proc = subprocess.run(
            [sys.executable, "-m", "docsync", "serve", "--registry", str(repo)],
            input="".join(json.dumps(m) + "\n" for m in messages),
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert proc.returncode == 0
        lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
        # Three replies, not four: the notification is answered with silence.
        assert len(lines) == 3
        responses = [json.loads(ln) for ln in lines]
        assert [r["id"] for r in responses] == [1, 2, 3]
        assert {t["name"] for t in responses[1]["result"]["tools"]} == set(HANDLERS)
        assert "retry.max_attempts" in responses[2]["result"]["content"][0]["text"]

    def test_stdout_carries_only_protocol_messages(self, repo: Path):
        # A stray print breaks the transport in a way that looks like the
        # server hanging. Verbose logging must go to stderr.
        proc = subprocess.run(
            [sys.executable, "-m", "docsync", "--verbose", "serve", "--registry", str(repo)],
            input=json.dumps(
                {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                 "params": {"name": "docsync_audit", "arguments": {}}}
            ) + "\n",
            capture_output=True,
            text=True,
            timeout=60,
        )
        for line in proc.stdout.splitlines():
            if line.strip():
                json.loads(line)  # every line must parse as JSON-RPC

    def test_messages_never_contain_a_raw_newline(self, repo: Path):
        # Multi-line plans are the normal output here, and the framing is
        # newline-delimited. json.dumps escapes them; indent= would not.
        proc = subprocess.run(
            [sys.executable, "-m", "docsync", "serve", "--registry", str(repo)],
            input=json.dumps(
                {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                 "params": {"name": "docsync_audit", "arguments": {}}}
            ) + "\n",
            capture_output=True,
            text=True,
            timeout=60,
        )
        payload = json.loads(proc.stdout.strip())
        assert "\n" in payload["result"]["content"][0]["text"]
        assert len(proc.stdout.strip().splitlines()) == 1
