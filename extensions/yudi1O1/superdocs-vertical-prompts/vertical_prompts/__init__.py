"""Vertical workflow-prompt packs for the SuperDocs MCP server.

A "pack" is a small YAML spec describing a set of MCP prompts (slash commands)
for one vertical. This package loads a pack spec and serves it as its own MCP
server — layered alongside SuperDocs' own MCP server, one client-config entry
per pack.
"""

__version__ = "0.1.0"
