from backend.workflow import apply_local_decisions


def test_human_decisions_are_item_by_item_and_preserve_rejections():
    original = "<p>A</p><p>B</p>"
    checkpoint = {
        "workflow_status": "awaiting_human_approval",
        "original_html": original,
        "changes": [
            {"change_id": "a", "operation": "edit", "old_html": "<p>A</p>", "new_html": "<p>A approved</p>"},
            {"change_id": "b", "operation": "edit", "old_html": "<p>B</p>", "new_html": "<p>B rejected</p>"},
        ],
    }
    result = apply_local_decisions(checkpoint, {"a": "approve", "b": "reject"})
    assert result["workflow_status"] == "approved"
    assert result["updated_html"] == "<p>A approved</p><p>B</p>"
    assert [c["change_id"] for c in result["approved_changes"]] == ["a"]
    assert [c["change_id"] for c in result["rejected_changes"]] == ["b"]
