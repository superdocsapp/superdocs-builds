"""
Unit and integration tests for SuperDocs Sessions API and tools
(matching https://docs.superdocs.app/concepts/sessions).
"""

import json
import pytest
from superdocs_langchain.client import SuperDocsClient
from superdocs_langchain.tools import (
    SuperDocsChatTool,
    SuperDocsListSessionsTool,
    SuperDocsSessionHistoryTool,
    SuperDocsSessionRevertTool,
)


def test_session_lifecycle_and_persistence(client: SuperDocsClient):
    session_id = "project-proposal-v1"

    # Turn 1: Starts a new session with initial HTML
    res1 = client.chat(
        message="Add an introduction section",
        session_id=session_id,
        document_html="<h1>Project Proposal</h1>",
    )
    assert res1.success is True
    assert res1.data["session_id"] == session_id
    assert "Introduction" in res1.data["document_state"]["document_html"]
    assert res1.data["turn_index"] == 1

    # Turn 2: Continues the same session without re-sending document_html
    res2 = client.chat(
        message="Now add a budget section",
        session_id=session_id,
    )
    assert res2.success is True
    doc_html = res2.data["document_state"]["document_html"]
    # AI remembers and preserves introduction while adding budget section
    assert "Introduction" in doc_html
    assert "Budget" in doc_html
    assert res2.data["turn_index"] == 3


def test_list_sessions(client: SuperDocsClient):
    client.chat(message="Draft contract", session_id="user_123_draft-contract", document_html="<h1>Contract</h1>")
    client.chat(message="Take notes", session_id="user_456_meeting-notes", document_html="<h1>Notes</h1>")

    list_res = client.list_sessions()
    assert list_res.success is True
    sessions = list_res.data["sessions"]
    assert len(sessions) >= 2
    session_ids = [s["session_id"] for s in sessions]
    assert "user_123_draft-contract" in session_ids
    assert "user_456_meeting-notes" in session_ids


def test_get_session_history(client: SuperDocsClient):
    session_id = "history-test-session"
    client.chat(message="First turn: Introduction", session_id=session_id, document_html="<h1>Doc</h1>")
    client.chat(message="Second turn: Conclusion", session_id=session_id)

    history_res = client.get_session_history(session_id=session_id)
    assert history_res.success is True
    data = history_res.data
    assert data["session_id"] == session_id
    assert len(data["messages"]) == 4  # 2 user + 2 assistant
    assert data["messages"][0]["role"] == "user"
    assert data["messages"][0]["turn_index"] == 0
    assert data["messages"][0]["checkpoint_id"] is not None
    assert "document_state" in data
    assert data["editor_action"] == "update"


def test_revert_session_to_previous_message(client: SuperDocsClient):
    session_id = "revert-demo-session"

    # Turn 0 (User), Turn 1 (AI)
    client.chat(message="Add section 1", session_id=session_id, document_html="<h1>Doc</h1>")
    
    # Turn 2 (User), Turn 3 (AI)
    client.chat(message="Add section 2 with incorrect pricing", session_id=session_id)

    # Revert session to turn_index 2 (undo the second user message)
    revert_res = client.revert_session(session_id=session_id, turn_index=2)
    assert revert_res.success is True
    data = revert_res.data
    assert data["compose_text"] == "Add section 2 with incorrect pricing"
    assert data["reverted_to_turn"] == 1
    assert data["archived_turn_count"] >= 2
    assert "Section 2" not in data["document_state"]["document_html"]

    # Subsequent history only shows the restored state
    history = client.get_session_history(session_id=session_id).data
    assert len(history["messages"]) == 2


def test_session_langchain_tools(client: SuperDocsClient):
    session_id = "tool-session-test"

    chat_tool = SuperDocsChatTool(client=client)
    res_str = chat_tool.invoke({
        "message": "Add an architecture section",
        "session_id": session_id,
        "document_html": "<h1>System Design</h1>",
    })
    res = json.loads(res_str)
    assert res["success"] is True
    assert "Architecture" in res["data"]["document_state"]["document_html"]

    # History tool
    hist_tool = SuperDocsSessionHistoryTool(client=client)
    h_res = json.loads(hist_tool.invoke({"session_id": session_id}))
    assert h_res["success"] is True
    assert len(h_res["data"]["messages"]) == 2

    # List tool
    list_tool = SuperDocsListSessionsTool(client=client)
    l_res = json.loads(list_tool.invoke({}))
    assert l_res["success"] is True
    assert any(s["session_id"] == session_id for s in l_res["data"]["sessions"])

    # Revert tool
    revert_tool = SuperDocsSessionRevertTool(client=client)
    r_res = json.loads(revert_tool.invoke({"session_id": session_id, "turn_index": 0}))
    assert r_res["success"] is True
    assert r_res["data"]["reverted_to_turn"] == -1
