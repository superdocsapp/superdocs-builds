"""
Unit tests for LangChain BaseTool implementations.
"""

import json
import pytest
from superdocs_langchain.client import SuperDocsClient
from superdocs_langchain.toolkit import SuperDocsToolkit
from superdocs_langchain.tools import (
    SuperDocsCommentTool,
    SuperDocsCreateDocumentTool,
    SuperDocsEditSectionTool,
    SuperDocsExportTool,
    SuperDocsGetDocumentTool,
    SuperDocsHistoryTool,
    SuperDocsSearchTool,
    SuperDocsTemplateRenderTool,
)


def test_toolkit_tools_list(toolkit: SuperDocsToolkit):
    tools = toolkit.get_tools()
    assert len(tools) == 12
    names = [t.name for t in tools]
    assert "superdocs_create_document" in names
    assert "superdocs_get_document" in names
    assert "superdocs_edit_section" in names
    assert "superdocs_search" in names
    assert "superdocs_render_template" in names
    assert "superdocs_export_document" in names
    assert "superdocs_add_comment" in names
    assert "superdocs_get_history" in names
    assert "superdocs_chat" in names
    assert "superdocs_list_sessions" in names
    assert "superdocs_get_session_history" in names
    assert "superdocs_revert_session" in names


def test_create_and_get_document_tool(client: SuperDocsClient):
    create_tool = SuperDocsCreateDocumentTool(client=client)
    res_str = create_tool.invoke({
        "title": "LangChain Agent Architecture",
        "content": "# Agent Core\nLangGraph orchestrator\n\n## Tools\nSuperDocs Toolkit",
    })
    res = json.loads(res_str)
    assert res["success"] is True
    doc_id = res["data"]["id"]

    get_tool = SuperDocsGetDocumentTool(client=client)
    get_res_str = get_tool.invoke({"document_id": doc_id, "include_outline": True})
    get_res = json.loads(get_res_str)
    assert get_res["success"] is True
    assert get_res["data"]["title"] == "LangChain Agent Architecture"
    assert "outline" in get_res["data"]


def test_edit_section_tool(client: SuperDocsClient):
    create_tool = SuperDocsCreateDocumentTool(client=client)
    create_res = json.loads(create_tool.invoke({
        "title": "Roadmap 2026",
        "content": "## Milestone 1\nAlpha release\n\n## Milestone 2\nBeta release",
    }))
    doc_id = create_res["data"]["id"]

    edit_tool = SuperDocsEditSectionTool(client=client)
    edit_res = json.loads(edit_tool.invoke({
        "document_id": doc_id,
        "section_target": "Milestone 1",
        "content": "Alpha release with 100% test coverage and MCP support.",
        "mode": "replace",
    }))
    assert edit_res["success"] is True
    assert "MCP support" in edit_res["data"]["content"]


def test_search_tool(populated_client: SuperDocsClient):
    search_tool = SuperDocsSearchTool(client=populated_client)
    res_str = search_tool.invoke({"query": "Consistent Hashing", "top_k": 3})
    res = json.loads(res_str)
    assert res["success"] is True
    assert len(res["data"]["results"]) > 0
    assert "Database Sharding Strategy" in res["data"]["results"][0]["title"]


def test_render_template_tool(client: SuperDocsClient):
    tmpl_tool = SuperDocsTemplateRenderTool(client=client)
    res_str = tmpl_tool.invoke({
        "template_id": "pr-description",
        "variables": {
            "title": "feat: SuperDocs LangChain Tools",
            "changes": "Implemented 8 typed tools and StateGraph",
            "testing": "Pytest suite passing",
        },
        "target_title": "PR Description: SuperDocs LangChain",
    })
    res = json.loads(res_str)
    assert res["success"] is True
    assert "feat: SuperDocs LangChain Tools" in res["data"]["content"]


def test_export_tool(client: SuperDocsClient):
    create_tool = SuperDocsCreateDocumentTool(client=client)
    create_res = json.loads(create_tool.invoke({"title": "HTML Export Test", "content": "## Section\nHello world"}))
    doc_id = create_res["data"]["id"]

    export_tool = SuperDocsExportTool(client=client)
    res_str = export_tool.invoke({"document_id": doc_id, "export_format": "html"})
    res = json.loads(res_str)
    assert res["success"] is True
    assert "<html>" in res["data"]["content"]


def test_comment_and_history_tool(client: SuperDocsClient):
    create_tool = SuperDocsCreateDocumentTool(client=client)
    doc_id = json.loads(create_tool.invoke({"title": "Review Target", "content": "## Draft\nUnder review."}))["data"]["id"]

    comment_tool = SuperDocsCommentTool(client=client)
    c_res = json.loads(comment_tool.invoke({
        "document_id": doc_id,
        "content": "Please verify section numbering.",
        "author": "langgraph-reviewer",
    }))
    assert c_res["success"] is True

    history_tool = SuperDocsHistoryTool(client=client)
    h_res = json.loads(history_tool.invoke({"document_id": doc_id}))
    assert h_res["success"] is True
    assert len(h_res["data"]["versions"]) >= 1


@pytest.mark.asyncio
async def test_async_tool_execution(client: SuperDocsClient):
    create_tool = SuperDocsCreateDocumentTool(client=client)
    res_str = await create_tool.ainvoke({"title": "Async Document", "content": "## Async\nCreated asynchronously"})
    res = json.loads(res_str)
    assert res["success"] is True
    assert res["data"]["title"] == "Async Document"
