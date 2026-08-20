"""MCP server exposing this workflow as a tool a coding agent or another
program can drive without clicking through any UI -- satisfies behavior
#4 (a machine can drive it) the same way the SuperDocs MCP surface does.
"""
from __future__ import annotations

import asyncio
import json

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

import app.api.main as api
from app.mcp.oauth import OAuthServer

server = Server("box-metadata-writeback")
_oauth = OAuthServer()

# Demo convenience only: seed one sample file so the probe script has
# something real to process without a live Box tenant. A production
# deployment points api._box at a real BoxClient instead.
api._box.seed_file(
    "mcp-demo-1",
    "sample-msa.pdf",
    b"SERVICES AGREEMENT\nCounterparty: Northwind Traders\nEffective Date: 2026-03-01\nValue: $50,000\n",
)


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="get_demo_access_token",
            description=(
                "Runs the OAuth authorization-code flow for the demo client "
                "and returns a bearer access token. Call this once before "
                "process_box_file; token is valid for 1 hour."
            ),
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="process_box_file",
            description=(
                "Run the classify/extract/companion-doc/normalize pipeline "
                "on a Box file and write results back to its metadata "
                "template. Idempotent per file version; respects legal "
                "hold and retention locks; never overrides governance "
                "fields. Requires a valid access_token from "
                "get_demo_access_token."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "file_id": {"type": "string"},
                    "access_token": {"type": "string"},
                },
                "required": ["file_id", "access_token"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "get_demo_access_token":
        code = _oauth.authorize("demo-agent-client")
        token = _oauth.exchange_code_for_token(code, "demo-agent-client", "demo-agent-secret")
        return [TextContent(type="text", text=json.dumps({"access_token": token}))]

    if name != "process_box_file":
        raise ValueError(f"unknown tool {name}")

    if not _oauth.verify(arguments.get("access_token")):
        # A machine driving this tool without a valid token is refused --
        # this is the enforcement point behavior #4 ("approval is an
        # operation your machine interface exposes") extends to: the
        # machine interface itself is gated, not just the human review
        # step inside the pipeline.
        return [
            TextContent(
                type="text",
                text=json.dumps({"error": "unauthorized: missing or expired access_token"}),
            )
        ]

    file_id = arguments["file_id"]
    report = api._pipeline.process(file_id)
    result = {
        "status": "skipped" if report.skipped_reason else "processed",
        "skipped_reason": report.skipped_reason,
        "file_id": report.file_id,
        "version_sha1": report.version_sha1,
        "stages": [s.__dict__ for s in report.stages],
        "metadata_written": report.metadata_written,
        "total_operations": report.total_operations,
    }
    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
