"""One-off diagnostic script. Run this BEFORE trusting SuperDocsMCPClient
with anything — it connects to the real SuperDocs MCP server (mcp v2 SDK),
prints every tool's real schema, then makes ONE real `chat` call and prints
the raw response so we can confirm exact response field names (document_id,
html, url, etc.) before hardcoding them anywhere.

Usage:
    python scripts\\inspect_mcp_tools.py
"""
import asyncio
import json
import sys
from pathlib import Path

# Ensure the project root (parent of this scripts\ folder) is importable,
# regardless of the working directory this script is invoked from.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from src.config import SUPERDOCS_API_KEY, SUPERDOCS_MCP_URL


async def main():
    # mcp v2: streamable_http_client no longer takes headers= directly.
    # Auth lives on the httpx2.AsyncClient you build and hand it.
    async with httpx2.AsyncClient(
        headers={"Authorization": f"Bearer {SUPERDOCS_API_KEY}"},
        timeout=httpx2.Timeout(30.0, read=300.0),
        follow_redirects=True,
    ) as http_client:
        transport = streamable_http_client(SUPERDOCS_MCP_URL, http_client=http_client)

        async with Client(transport) as client:
            print("=" * 60)
            print("AVAILABLE TOOLS AND THEIR REAL SCHEMAS")
            print("=" * 60)
            tools_result = await client.list_tools()
            for tool in tools_result.tools:
                print(f"\n--- {tool.name} ---")
                print(f"Description: {tool.description}")
                print(f"Input schema: {json.dumps(tool.input_schema, indent=2)}")

            print("\n" + "=" * 60)
            print("ONE REAL CHAT CALL — creating a tiny test document")
            print("=" * 60)
            result = await client.call_tool("chat", {
                "session_id": "diagnostic-test-session",
                "message": "This is a connectivity test. Do not make any changes, just confirm you loaded the document.",
                "document_html": "<h2>Test Section</h2><p>Placeholder.</p>",
            })
            print(f"isError: {result.is_error}")
            print(f"structured_content:\n{json.dumps(result.structured_content, indent=2) if result.structured_content else None}")
            for block in result.content:
                if hasattr(block, "text"):
                    print(f"\nContent block text:\n{block.text}")

            print("\n" + "=" * 60)
            print("ONE REAL request_download_url CALL")
            print("=" * 60)
            download_result = await client.call_tool("request_download_url", {
                "session_id": "diagnostic-test-session",
                "format": "html",
            })
            print(f"isError: {download_result.is_error}")
            print(f"structured_content:\n{json.dumps(download_result.structured_content, indent=2) if download_result.structured_content else None}")


if __name__ == "__main__":
    asyncio.run(main())