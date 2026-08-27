"""Serves one vertical pack as its own MCP server (prompts only — no tools).

Run it directly:

    python -m vertical_prompts.server --pack packs/legal/pack.yaml

This is the "one entry in a client configuration" build: point Claude Code /
Claude Desktop / Cursor's MCP config at this command, and the pack's commands
appear as `/pack_id:command_id` slash commands, alongside whatever SuperDocs
MCP tools that same client already has connected.
"""
from __future__ import annotations

import argparse
import sys

import mcp.server.stdio
import mcp.types as types
from mcp.server.lowlevel import NotificationOptions, Server
from mcp.server.models import InitializationOptions
from mcp.shared.exceptions import McpError

from .pack_spec import ArgumentError, CommandSpec, PackSpec, load_pack, render_full_prompt


def _mcp_prompt_argument(arg) -> types.PromptArgument:
    return types.PromptArgument(name=arg.name, description=arg.description, required=arg.required)


def _mcp_prompt(command: CommandSpec) -> types.Prompt:
    return types.Prompt(
        name=command.id,
        title=command.title,
        description=command.description,
        arguments=[_mcp_prompt_argument(a) for a in command.arguments],
    )


def build_server(pack: PackSpec) -> Server:
    server = Server(f"superdocs-{pack.pack_id}-prompts")

    @server.list_prompts()
    async def list_prompts() -> list[types.Prompt]:
        return [_mcp_prompt(c) for c in pack.commands]

    @server.get_prompt()
    async def get_prompt(name: str, arguments: dict[str, str] | None) -> types.GetPromptResult:
        command = pack.get_command(name)
        if command is None:
            known = sorted(c.id for c in pack.commands)
            raise McpError(
                types.ErrorData(
                    code=types.INVALID_PARAMS,
                    message=f"Unknown prompt '{name}' in pack '{pack.pack_id}'. Known commands: {known}",
                )
            )
        try:
            text = render_full_prompt(command, arguments or {})
        except ArgumentError as e:
            # This is the "helpful error" the task card asks for: the exact
            # missing/invalid argument, not a generic 400. Every MCP client
            # surfaces McpError.message directly to the user.
            raise McpError(types.ErrorData(code=types.INVALID_PARAMS, message=str(e)))

        return types.GetPromptResult(
            description=command.description,
            messages=[types.PromptMessage(role="user", content=types.TextContent(type="text", text=text))],
        )

    return server


async def run_stdio(pack: PackSpec) -> None:
    server = build_server(pack)
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name=f"superdocs-{pack.pack_id}-prompts",
                server_version="0.1.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="vertical_prompts.server")
    parser.add_argument("--pack", required=True, help="Path to a pack.yaml file.")
    args = parser.parse_args(argv)

    pack = load_pack(args.pack)

    import anyio

    anyio.run(run_stdio, pack)
    return 0


if __name__ == "__main__":
    sys.exit(main())
