from superdocs_adapter import (
    ToolDefinition,
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
            {"document_id": document_id, "instruction": instruction},
        )

    def search_document(
        self,
        document_id: str,
        query: str,
        **kwargs: object,
    ) -> ToolResult:
        return ToolResult.ok(
            ToolName.SEARCH_DOCUMENT,
            {"document_id": document_id, "query": query},
        )

    def export_document(
        self,
        document_id: str,
        format: str = "docx",
        **kwargs: object,
    ) -> ToolResult:
        return ToolResult.ok(
            ToolName.EXPORT_DOCUMENT,
            {"document_id": document_id, "format": format},
        )


def test_create_tool_definitions() -> None:
    adapter = FakeAdapter()

    tools = create_tool_definitions(adapter)

    assert set(tools) == {
        ToolName.EDIT_DOCUMENT,
        ToolName.SEARCH_DOCUMENT,
        ToolName.EXPORT_DOCUMENT,
    }

    assert all(isinstance(tool, ToolDefinition) for tool in tools.values())


def test_edit_tool_executes_adapter_method() -> None:
    adapter = FakeAdapter()
    tools = create_tool_definitions(adapter)

    result = tools[ToolName.EDIT_DOCUMENT].execute(
        document_id="doc-123",
        instruction="Update the introduction.",
    )

    assert result.success is True
    assert result.tool is ToolName.EDIT_DOCUMENT
    assert result.data == {
        "document_id": "doc-123",
        "instruction": "Update the introduction.",
    }


def test_search_tool_executes_adapter_method() -> None:
    adapter = FakeAdapter()
    tools = create_tool_definitions(adapter)

    result = tools[ToolName.SEARCH_DOCUMENT].execute(
        document_id="doc-123",
        query="authentication",
    )

    assert result.success is True
    assert result.tool is ToolName.SEARCH_DOCUMENT


def test_export_tool_executes_adapter_method() -> None:
    adapter = FakeAdapter()
    tools = create_tool_definitions(adapter)

    result = tools[ToolName.EXPORT_DOCUMENT].execute(
        document_id="doc-123",
        format="docx",
    )

    assert result.success is True
    assert result.tool is ToolName.EXPORT_DOCUMENT
