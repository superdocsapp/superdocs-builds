"""Tests for MCP (Model Context Protocol) Server Tools."""

import pytest
from app.db.session import SessionLocal
from app.models.finding import Finding
from app.models.submittal import Submittal
from app.mcp_server import handle_tool_call, TOOLS


@pytest.fixture(autouse=True)
def setup_teardown_db():
    db = SessionLocal()
    # Clean up any existing test records first
    existing = db.query(Submittal).filter(Submittal.number == "SUB-MCP").first()
    if existing:
        db.query(Finding).filter(Finding.submittal_id == existing.id).delete()
        db.delete(existing)
        db.commit()

    s = Submittal(
        project_id="MCP-PROJ",
        number="SUB-MCP",
        title="MCP Test Submittal",
        specification_section="09 65 00",
        status="PENDING",
        register_status="NOT_RECEIVED",
    )
    db.add(s)
    db.flush()
    f = Finding(
        submittal_id=s.id,
        attribute="Test Attribute",
        requirement="Required",
        submitted_value="Submitted",
        result="MATCH",
        specification_evidence="Spec Evidence",
        submission_evidence="Submission Evidence",
        status="PENDING_REVIEW",
    )
    db.add(f)
    db.commit()
    db.close()

    yield

    # Cleanup after test
    db2 = SessionLocal()
    existing2 = db2.query(Submittal).filter(Submittal.number == "SUB-MCP").first()
    if existing2:
        db2.query(Finding).filter(Finding.submittal_id == existing2.id).delete()
        db2.delete(existing2)
        db2.commit()
    db2.close()


def test_tools_list_schema():
    assert len(TOOLS) >= 6
    tool_names = [t["name"] for t in TOOLS]
    assert "list_submittals" in tool_names
    assert "get_submittal_detail" in tool_names
    assert "review_finding" in tool_names
    assert "search_project" in tool_names
    assert "chat_project" in tool_names


def test_mcp_list_submittals():
    res = handle_tool_call("list_submittals", {"project_id": "MCP-PROJ"})
    assert "items" in res
    assert any(i["number"] == "SUB-MCP" for i in res["items"])


def test_mcp_get_submittal_detail():
    res = handle_tool_call("get_submittal_detail", {"submittal_number": "SUB-MCP"})
    assert res["number"] == "SUB-MCP"
    assert len(res["findings"]) == 1


def test_mcp_search_project():
    res = handle_tool_call("search_project", {"project_id": "MCP-PROJ", "query": "MCP"})
    assert res["total_count"] >= 1


def test_mcp_chat_project():
    res = handle_tool_call("chat_project", {"project_id": "MCP-PROJ", "query": "What is the status of SUB-MCP?"})
    assert "SUB-MCP" in res["answer"]
