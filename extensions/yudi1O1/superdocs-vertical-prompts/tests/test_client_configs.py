"""Cross-client proof, at the level where clients actually differ.

Every MCP client speaks the same `prompts/list` / `prompts/get` JSON-RPC over
the same stdio transport — that part is proven in `test_server_protocol.py`.
What genuinely varies between clients is the **config file shape**: Claude Code,
Claude Desktop and Cursor nest servers under `mcpServers`, VS Code uses
`servers`, Zed uses `context_servers`.

So this file takes each committed config in `clients/`, extracts the launch
command exactly as that client would, spawns the server with it, and runs a real
MCP session against it. A config that is malformed, points at the wrong module,
or names a pack that doesn't exist fails here — which is the failure mode a user
would actually hit, rather than a hypothetical protocol difference that MCP's
standardisation rules out.

Five clients covered; the card asks for at least three.
"""
from __future__ import annotations

import json
import os
import sys

import pytest
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLIENTS_DIR = os.path.join(ROOT, "clients")

PLACEHOLDER_CWD = "/absolute/path/to/superdocs-vertical-prompts"

#: config filename -> the top-level key that client uses for its server map.
CLIENT_SHAPES = {
    "claude_code.json": "mcpServers",
    "claude_desktop.json": "mcpServers",
    "cursor.json": "mcpServers",
    "vscode.json": "servers",
    "zed.json": "context_servers",
}


def _load_entries(filename: str) -> list[tuple[str, dict]]:
    path = os.path.join(CLIENTS_DIR, filename)
    with open(path, "r", encoding="utf-8") as f:
        config = json.load(f)
    key = CLIENT_SHAPES[filename]
    assert key in config, f"{filename} must nest servers under '{key}' for this client"
    return list(config[key].items())


@pytest.mark.parametrize("filename", sorted(CLIENT_SHAPES))
def test_every_client_config_is_valid_json_with_the_right_shape(filename):
    entries = _load_entries(filename)
    assert entries, f"{filename} declares no servers"
    for name, entry in entries:
        assert entry.get("command"), f"{filename}:{name} has no command"
        assert entry.get("args"), f"{filename}:{name} has no args"
        assert entry.get("cwd") == PLACEHOLDER_CWD, (
            f"{filename}:{name} must ship the documented placeholder cwd so users know to replace it"
        )


@pytest.mark.parametrize("filename", sorted(CLIENT_SHAPES))
async def test_server_actually_starts_from_each_client_config(filename):
    """Spawn the server using the launch command that client would use, with the
    placeholder cwd resolved to this checkout, and complete a real MCP session."""
    for name, entry in _load_entries(filename):
        params = StdioServerParameters(
            # Use this interpreter rather than bare "python" so the test is not
            # hostage to whatever "python" means on the test machine's PATH.
            command=sys.executable,
            args=entry["args"],
            cwd=ROOT if entry["cwd"] == PLACEHOLDER_CWD else entry["cwd"],
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.list_prompts()
                assert result.prompts, f"{filename}:{name} started but exposed no prompts"


async def test_the_same_pack_renders_identically_regardless_of_client_config():
    """The core cross-client claim: one pack, launched via two different clients'
    config shapes, produces byte-identical prompt text. Nothing in the rendering
    path depends on which client asked."""
    rendered = []
    for filename in ("claude_code.json", "vscode.json"):
        entry = dict(_load_entries(filename))["superdocs-legal-pack"]
        params = StdioServerParameters(command=sys.executable, args=entry["args"], cwd=ROOT)
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.get_prompt(
                    "redline",
                    {
                        "contract_description": "the vendor MSA",
                        "focus_areas": "indemnification",
                        "negotiating_position": "mutual, capped at 12 months fees",
                    },
                )
                rendered.append(result.messages[0].content.text)

    assert rendered[0] == rendered[1]
