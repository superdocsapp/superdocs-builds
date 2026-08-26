"""Pure rendering tests — no DB, no network."""
from app.slack.home_tab import build_home_tab_view


def test_empty_state_renders_all_four_empty_sections():
    view = build_home_tab_view()
    text = " ".join(
        b["text"]["text"] for b in view["blocks"] if b["type"] == "section" and "text" in b
    )
    assert "No documents open yet" in text
    assert "Nothing pending" in text
    assert "Nothing running" in text
    assert "Nothing exported yet" in text


def test_populated_state_renders_each_section():
    view = build_home_tab_view(
        open_documents=[{"title": "Status Report", "superdocs_document_id": "doc_1"}],
        pending_approvals=[{"job_id": "job_1", "change_id": "chg_1", "ai_explanation": "Reformatted the due-dates list"}],
        running_jobs=[{"job_id": "job_1", "status": "in_progress"}],
        recent_output=[{"id": 1, "export_format": "docx"}],
    )
    text = " ".join(
        b["text"]["text"] for b in view["blocks"] if b["type"] == "section" and "text" in b
    )
    assert "Status Report" in text
    assert "Reformatted the due-dates list" in text
    assert "job_1" in text
    assert "DOCX export" in text
