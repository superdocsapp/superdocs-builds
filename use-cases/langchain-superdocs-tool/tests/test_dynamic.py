"""
Unit tests for Dynamic Tool Binding from OpenAPI and MCP manifests.
"""

import json
from superdocs_langchain.client import SuperDocsClient
from superdocs_langchain.dynamic import (
    build_dynamic_tool,
    load_dynamic_superdocs_tools,
    load_tools_from_mcp_manifest,
)


def test_load_dynamic_tools_from_client(client: SuperDocsClient):
    dynamic_tools = load_dynamic_superdocs_tools(client)
    assert len(dynamic_tools) >= 7
    tool_names = [t.name for t in dynamic_tools]
    assert "superdocs_create_document" in tool_names
    assert "superdocs_get_document" in tool_names
    assert "superdocs_edit_section" in tool_names
    assert "superdocs_search" in tool_names


def test_dynamic_tool_invocation(client: SuperDocsClient):
    dynamic_tools = load_dynamic_superdocs_tools(client)
    create_tool = next(t for t in dynamic_tools if t.name == "superdocs_create_document")
    
    res_str = create_tool.invoke({
        "title": "Dynamic Doc Test",
        "content": "## Heading\nDynamic content.",
    })
    res = json.loads(res_str)
    assert res["success"] is True
    assert res["data"]["title"] == "Dynamic Doc Test"
    doc_id = res["data"]["id"]

    # Test dynamic search
    search_tool = next(t for t in dynamic_tools if t.name == "superdocs_search")
    s_res = json.loads(search_tool.invoke({"query": "Dynamic Doc"}))
    assert s_res["success"] is True
    assert len(s_res["data"]["results"]) > 0


def test_load_from_mcp_manifest(client: SuperDocsClient):
    mcp_manifest = {
        "tools": [
            {
                "name": "superdocs_create_document",
                "description": "MCP standard create document tool",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "Document title"},
                        "content": {"type": "string", "description": "Body markdown"},
                    },
                    "required": ["title"],
                },
            },
            {
                "name": "superdocs_search",
                "description": "MCP search tool",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Query text"},
                    },
                    "required": ["query"],
                },
            },
        ]
    }

    tools = load_tools_from_mcp_manifest(mcp_manifest, client)
    assert len(tools) == 2
    assert tools[0].name == "superdocs_create_document"
    assert tools[1].name == "superdocs_search"

    res_str = tools[0].invoke({"title": "MCP Generated Doc", "content": "Hello from MCP schema"})
    res = json.loads(res_str)
    assert res["success"] is True
    assert res["data"]["title"] == "MCP Generated Doc"
