import pytest

from superdocs_adapter import ToolName, ToolResult


def test_tool_result_ok() -> None:
    result = ToolResult.ok(
        ToolName.EDIT_DOCUMENT,
        {"changes": []},
    )

    assert result.tool is ToolName.EDIT_DOCUMENT
    assert result.success is True
    assert result.data == {"changes": []}
    assert result.error is None


def test_tool_result_failure() -> None:
    result = ToolResult.failure(
        ToolName.SEARCH_DOCUMENT,
        "Search is unavailable.",
    )

    assert result.tool is ToolName.SEARCH_DOCUMENT
    assert result.success is False
    assert result.data is None
    assert result.error == "Search is unavailable."


def test_tool_names_are_stable_strings() -> None:
    assert ToolName.EDIT_DOCUMENT.value == "edit_document"
    assert ToolName.SEARCH_DOCUMENT.value == "search_document"
    assert ToolName.EXPORT_DOCUMENT.value == "export_document"


def test_success_result_unwraps_data() -> None:
    result = ToolResult.ok(
        ToolName.SEARCH_DOCUMENT,
        {"matches": ["authentication"]},
    )

    assert result.unwrap() == {
        "matches": ["authentication"],
    }


def test_failure_result_unwrap_raises() -> None:
    result = ToolResult.failure(
        ToolName.SEARCH_DOCUMENT,
        "Document not found.",
    )

    with pytest.raises(RuntimeError, match="Document not found"):
        result.unwrap()


def test_failure_result_has_no_data() -> None:
    result = ToolResult.failure(
        ToolName.EDIT_DOCUMENT,
        "API unavailable.",
    )

    assert result.success is False
    assert result.data is None
    assert result.error == "API unavailable."
