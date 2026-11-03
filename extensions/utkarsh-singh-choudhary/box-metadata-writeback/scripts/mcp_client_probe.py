"""Live probe: talks to the MCP server over real stdio MCP protocol,
proving behavior #4 (a machine can drive it) AND the OAuth extra-credit
surface end to end -- gets a token, then calls process_box_file with it,
then proves an unauthenticated call is refused."""
import asyncio
import json

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    params = StdioServerParameters(command="python3", args=["-m", "app.mcp.server"])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print("tools:", [t.name for t in tools.tools])

            # unauthenticated call is refused
            bad = await session.call_tool("process_box_file", {"file_id": "mcp-demo-1", "access_token": "not-a-real-token"})
            print("unauthenticated call ->", bad.content[0].text)

            # get a real token, then the call succeeds
            token_result = await session.call_tool("get_demo_access_token", {})
            token = json.loads(token_result.content[0].text)["access_token"]
            print("got access_token:", token[:12] + "...")

            result = await session.call_tool(
                "process_box_file", {"file_id": "mcp-demo-1", "access_token": token}
            )
            print("authenticated call ->", result.content[0].text)


if __name__ == "__main__":
    asyncio.run(main())
