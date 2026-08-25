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
            {
                "document_id": document_id,
                "instruction": instruction,
            },
        )

    def search_document(
        self,
        document_id: str,
        query: str,
        **kwargs: object,
    ) -> ToolResult:
        return ToolResult.ok(
            ToolName.SEARCH_DOCUMENT,
            {
                "document_id": document_id,
                "query": query,
            },
        )

    def export_document(
        self,
        document_id: str,
        format: str = "docx",
        **kwargs: object,
    ) -> ToolResult:
        return ToolResult.ok(
            ToolName.EXPORT_DOCUMENT,
            {
                "document_id": document_id,
                "format": format,
            },
        )


def test_llamaindex_integration() -> None:
    pytest.importorskip("llama_index.core")

    from superdocs_adapter.integrations.llamaindex import (
        create_llamaindex_tools,
    )

    definitions = create_tool_definitions(FakeAdapter())

    tools = create_llamaindex_tools(definitions)

    assert len(tools) == 3

    names = {tool.metadata.name for tool in tools}

    assert names == {
        "edit_document",
        "search_document",
        "export_document",
    }


def test_llamaindex_tool_executes_core_adapter() -> None:
    pytest.importorskip("llama_index.core")

    from superdocs_adapter.integrations.llamaindex import (
        create_llamaindex_tools,
    )

    definitions = create_tool_definitions(FakeAdapter())

    tools = create_llamaindex_tools(definitions)

    edit_tool = next(
        tool
        for tool in tools
        if tool.metadata.name == "edit_document"
    )

    result = edit_tool.call(
        document_id="doc-123",
        instruction="Update introduction.",
    )

    assert result.raw_output.success is True
    assert result.raw_output.tool is ToolName.EDIT_DOCUMENT
