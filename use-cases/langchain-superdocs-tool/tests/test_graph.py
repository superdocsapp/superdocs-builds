"""
End-to-end integration tests for LangGraph StateGraph document agent workflow.
"""

from superdocs_langchain.client import SuperDocsClient
from superdocs_langchain.graph import create_superdocs_agent_graph


def test_langgraph_tech_spec_workflow():
    client = SuperDocsClient(offline=True)
    graph = create_superdocs_agent_graph(client=client, dynamic_tools=False, max_iterations=10)

    initial_state = {
        "user_goal": "Create a technical architecture specification for a real-time event streaming pipeline",
        "tasks": [],
        "current_task_index": None,
        "current_task": None,
        "document_id": None,
        "document_title": None,
        "plan": None,
        "step": 0,
        "critique": None,
        "needs_revision": False,
        "iterations": 0,
        "max_iterations": 10,
        "export_format": "markdown",
        "final_output": None,
        "status": "initialized",
        "trace_logs": [],
    }

    final_state = graph.invoke(initial_state)

    assert final_state["status"] == "completed"
    assert final_state["document_id"] is not None
    assert len(final_state["tasks"]) >= 3
    assert all(t["status"] == "completed" for t in final_state["tasks"])
    assert final_state["final_output"] is not None


def test_langgraph_explicit_custom_task_list():
    """Verify that providing an explicit list of tasks executes each one to completion."""
    client = SuperDocsClient(offline=True)
    graph = create_superdocs_agent_graph(client=client, dynamic_tools=False, max_iterations=10)

    custom_tasks = [
        {
            "id": "t1_scaffold",
            "title": "Create Scaffold Doc",
            "tool_target": "superdocs_create_document",
            "tool_args": {"title": "Distributed Cache Doc", "content": "## Overview\nIn-memory tier."},
            "status": "pending",
        },
        {
            "id": "t2_add_section",
            "title": "Append Replication Section",
            "tool_target": "superdocs_edit_section",
            "tool_args": {"section_target": "Replication Strategy", "content": "Raft consensus with multi-AZ quorum.", "mode": "replace"},
            "status": "pending",
        },
        {
            "id": "t3_review_note",
            "title": "Attach Audit Note",
            "tool_target": "superdocs_add_comment",
            "tool_args": {"content": "Verified quorum calculations.", "author": "security-lead"},
            "status": "pending",
        },
    ]

    initial_state = {
        "user_goal": "Build distributed cache documentation",
        "tasks": custom_tasks,
        "current_task_index": None,
        "current_task": None,
        "document_id": None,
        "document_title": None,
        "plan": None,
        "step": 0,
        "critique": None,
        "needs_revision": False,
        "iterations": 0,
        "max_iterations": 10,
        "export_format": "markdown",
        "final_output": None,
        "status": "initialized",
        "trace_logs": [],
    }

    final_state = graph.invoke(initial_state)

    assert final_state["status"] == "completed"
    assert len(final_state["tasks"]) == 3
    assert all(t["status"] == "completed" for t in final_state["tasks"])
    assert "Raft consensus" in final_state["final_output"]


def test_langgraph_pr_workflow():
    client = SuperDocsClient(offline=True)
    graph = create_superdocs_agent_graph(client=client, dynamic_tools=False, max_iterations=10)

    initial_state = {
        "user_goal": "PR: Add SuperDocs LangChain BaseTool adapter",
        "tasks": [],
        "current_task_index": None,
        "current_task": None,
        "document_id": None,
        "document_title": None,
        "plan": None,
        "step": 0,
        "critique": None,
        "needs_revision": False,
        "iterations": 0,
        "max_iterations": 10,
        "export_format": "html",
        "final_output": None,
        "status": "initialized",
        "trace_logs": [],
    }

    final_state = graph.invoke(initial_state)

    assert final_state["status"] == "completed"
    assert "<html>" in final_state["final_output"]
    assert "SuperDocs" in final_state["final_output"]


def test_langgraph_with_dynamic_tools():
    client = SuperDocsClient(offline=True)
    graph = create_superdocs_agent_graph(client=client, dynamic_tools=True, max_iterations=10)

    initial_state = {
        "user_goal": "Create custom release notes for SuperDocs v2.0",
        "tasks": [],
        "current_task_index": None,
        "current_task": None,
        "document_id": None,
        "document_title": None,
        "plan": None,
        "step": 0,
        "critique": None,
        "needs_revision": False,
        "iterations": 0,
        "max_iterations": 10,
        "export_format": "markdown",
        "final_output": None,
        "status": "initialized",
        "trace_logs": [],
    }

    final_state = graph.invoke(initial_state)
    assert final_state["status"] == "completed"
    assert final_state["document_id"] is not None
    assert all(t["status"] == "completed" for t in final_state["tasks"])
