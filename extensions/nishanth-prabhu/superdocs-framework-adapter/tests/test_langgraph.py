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


def test_create_langgraph_nodes() -> None:
    from superdocs_adapter.integrations.langgraph import (
        create_langgraph_nodes,
    )

    definitions = create_tool_definitions(FakeAdapter())

    nodes = create_langgraph_nodes(definitions)

    assert set(nodes) == {
        "edit_document",
        "search_document",
        "export_document",
    }

    assert all(callable(node) for node in nodes.values())


def test_edit_langgraph_node() -> None:
    from superdocs_adapter.integrations.langgraph import (
        create_langgraph_nodes,
        execute_langgraph_node,
    )

    definitions = create_tool_definitions(FakeAdapter())
    nodes = create_langgraph_nodes(definitions)

    result = execute_langgraph_node(
        nodes["edit_document"],
        {
            "document_id": "doc-123",
            "instruction": "Update the introduction.",
        },
    )

    assert result.success is True
    assert result.tool is ToolName.EDIT_DOCUMENT
    assert result.data == {
        "document_id": "doc-123",
        "instruction": "Update the introduction.",
    }


def test_search_langgraph_node() -> None:
    from superdocs_adapter.integrations.langgraph import (
        create_langgraph_nodes,
        execute_langgraph_node,
    )

    definitions = create_tool_definitions(FakeAdapter())
    nodes = create_langgraph_nodes(definitions)

    result = execute_langgraph_node(
        nodes["search_document"],
        {
            "document_id": "doc-123",
            "query": "authentication",
        },
    )

    assert result.success is True
    assert result.tool is ToolName.SEARCH_DOCUMENT


def test_langgraph_node_rejects_invalid_result() -> None:
    from superdocs_adapter.integrations.langgraph import (
        execute_langgraph_node,
    )

    def invalid_node(state: dict[str, object]) -> dict[str, object]:
        return {"superdocs_result": "invalid"}

    try:
        execute_langgraph_node(invalid_node, {})
    except TypeError as exc:
        assert "ToolResult" in str(exc)
    else:
        raise AssertionError("Expected TypeError")
