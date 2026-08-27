"""Protocol-conformance tests: spawn the real server as a subprocess and drive
it with the official MCP client SDK over real stdio JSON-RPC — the same
transport and the same `ClientSession.list_prompts()` / `get_prompt()` calls
every MCP-compatible client (Claude Code, Claude Desktop, Cursor, Zed, ...)
uses. This is what "prompts work unchanged across at least three agent
clients" is actually testable as without literally scripting three separate
GUI applications: if a pack speaks correct MCP protocol here, any conformant
client renders it identically, because they all speak the same protocol —
that's the whole point of MCP as a standard. No live SuperDocs API key is
needed; prompts never call SuperDocs themselves, they only render text.

No mocking of the MCP SDK itself: this exercises the real stdio transport,
the real JSON-RPC framing, and the real server process.
"""
from __future__ import annotations

import os
import sys

import pytest
from mcp import types
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.shared.exceptions import McpError

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKS_DIR = os.path.join(ROOT, "packs")

LEGAL_PACK = os.path.join(PACKS_DIR, "legal", "pack.yaml")
REAL_ESTATE_PACK = os.path.join(PACKS_DIR, "real_estate", "pack.yaml")


def _server_params(pack_path: str) -> StdioServerParameters:
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "vertical_prompts.server", "--pack", pack_path],
        cwd=os.path.dirname(PACKS_DIR),
    )


@pytest.mark.parametrize("pack_path,expected_ids", [
    (LEGAL_PACK, {"redline", "fallback_clause", "draft_from_playbook", "obligation_summary"}),
    (REAL_ESTATE_PACK, {"draft_disclosure", "compare_addendum", "closing_checklist"}),
])
async def test_list_prompts_matches_pack_commands(pack_path, expected_ids):
    async with stdio_client(_server_params(pack_path)) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.list_prompts()
            got_ids = {p.name for p in result.prompts}
            assert got_ids == expected_ids


async def test_prompt_arguments_are_advertised_correctly():
    async with stdio_client(_server_params(LEGAL_PACK)) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.list_prompts()
            redline = next(p for p in result.prompts if p.name == "redline")
            arg_names = {a.name for a in redline.arguments}
            assert arg_names == {"contract_description", "focus_areas", "negotiating_position"}
            required = {a.name for a in redline.arguments if a.required}
            assert required == {"contract_description", "negotiating_position"}
            assert not next(a for a in redline.arguments if a.name == "focus_areas").required


async def test_get_prompt_renders_arguments_into_instruction():
    async with stdio_client(_server_params(LEGAL_PACK)) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.get_prompt(
                "redline",
                {
                    "contract_description": "the vendor MSA open in this session",
                    "focus_areas": "indemnification",
                    "negotiating_position": "mutual indemnification capped at 12 months fees",
                },
            )
            assert len(result.messages) == 1
            text = result.messages[0].content.text
            assert "the vendor MSA open in this session" in text
            assert "indemnification" in text
            assert "mutual indemnification capped at 12 months fees" in text
            # approval-mode guidance for ask_every_time must be present, since this
            # is what tells the assistant NOT to auto-apply a redline.
            assert "chat_async" in text
            assert "ask_every_time" in text
            assert "approve_change" in text


async def test_get_prompt_missing_required_argument_raises_helpful_mcp_error():
    async with stdio_client(_server_params(LEGAL_PACK)) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            with pytest.raises(McpError) as exc_info:
                await session.get_prompt("redline", {"contract_description": "the MSA"})
            message = str(exc_info.value)
            # A helpful error names the specific missing argument, not a generic 400.
            assert "negotiating_position" in message
            assert exc_info.value.error.code == types.INVALID_PARAMS


async def test_get_prompt_unknown_prompt_name_raises_helpful_mcp_error():
    async with stdio_client(_server_params(LEGAL_PACK)) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            with pytest.raises(McpError) as exc_info:
                await session.get_prompt("does_not_exist", {})
            assert "does_not_exist" in str(exc_info.value)
            assert "redline" in str(exc_info.value)  # lists known commands


async def test_approve_all_command_gets_different_guidance_than_ask_every_time():
    async with stdio_client(_server_params(LEGAL_PACK)) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.get_prompt(
                "obligation_summary", {"contract_description": "the vendor MSA"}
            )
            text = result.messages[0].content.text
            assert "approve_all" in text
            assert "export_document" in text
            assert 'format="markdown"' in text


async def test_real_estate_pack_scaffolded_from_template_is_fully_functional():
    """The second-vertical proof: this pack was generated by the scaffolder
    (see README) then hand-filled — this test proves the RESULT works through
    the same MCP server code path as the hand-written legal pack, not a
    special case."""
    async with stdio_client(_server_params(REAL_ESTATE_PACK)) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.get_prompt(
                "draft_disclosure",
                {
                    "property_description": "123 Maple St., built 1974",
                    "disclosure_type": "material defect disclosure",
                    "jurisdiction": "California",
                },
            )
            text = result.messages[0].content.text
            assert "123 Maple St." in text
            assert "California" in text
            assert "chat_async" in text  # ask_every_time guidance present
