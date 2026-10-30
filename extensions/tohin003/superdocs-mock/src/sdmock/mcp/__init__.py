"""The MCP half of the mock: Streamable HTTP, mounted at /mcp/ like the real service."""

from .server import MCPServer

__all__ = ["MCPServer"]
