from __future__ import annotations

import pytest

from superdocs_adapter import (
    ToolName,
    ToolResult,
    create_tool_definitions,
)


class FakeAdapter:
    def edit_document(
        self,
        document_id: str,
        instruction: str,
        **kwargs: object,
    ) -> ToolResult:
        return ToolResult.ok(
            ToolName.EDIT_DOCUMENT,
            {"document_id": document_id},
        )

    def search_document(
        self,
        document_id: str,
        query: str,
        **kwargs: object,
    ) -> ToolResult:
        return ToolResult.ok(
            ToolName.SEARCH_DOCUMENT,
            {"document_id": document_id},
        )

    def export_document(
        self,
        document_id: str,
        format: str = "docx",
        **kwargs: object,
    ) -> ToolResult:
        return ToolResult.ok(
            ToolName.EXPORT_DOCUMENT,
            {"document_id": document_id},
        )


EXPECTED_TOOLS = {
    ToolName.EDIT_DOCUMENT,
    ToolName.SEARCH_DOCUMENT,
    ToolName.EXPORT_DOCUMENT,
}


def test_core_tool_contract() -> None:
    definitions = create_tool_definitions(FakeAdapter())

    assert set(definitions) == EXPECTED_TOOLS


def test_langchain_contract() -> None:
    pytest.importorskip("langchain_core")

    from superdocs_adapter.integrations.langchain import (
        create_langchain_tools,
    )

    definitions = create_tool_definitions(FakeAdapter())
    tools = create_langchain_tools(definitions)

    assert {tool.name for tool in tools} == {
        tool.value for tool in EXPECTED_TOOLS
    }


def test_langgraph_contract() -> None:
    from superdocs_adapter.integrations.langgraph import (
        create_langgraph_nodes,
    )

    definitions = create_tool_definitions(FakeAdapter())
    nodes = create_langgraph_nodes(definitions)

    assert set(nodes) == {
        tool.value for tool in EXPECTED_TOOLS
    }


def test_llamaindex_contract() -> None:
    pytest.importorskip("llama_index.core")

    from superdocs_adapter.integrations.llamaindex import (
        create_llamaindex_tools,
    )

    definitions = create_tool_definitions(FakeAdapter())
    tools = create_llamaindex_tools(definitions)

    assert {
        tool.metadata.name
        for tool in tools
    } == {
        tool.value for tool in EXPECTED_TOOLS
    }
