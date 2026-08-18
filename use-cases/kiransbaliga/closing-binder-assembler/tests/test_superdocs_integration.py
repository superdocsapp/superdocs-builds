"""Tests for SuperDocs 4-call API contract, double-parse safety, and MCP server tools."""

import json
import os
import tempfile
import pytest

from superdocs.client import SuperDocsClient
from superdocs.mcp_server import ClosingBinderMCPServer


def test_superdocs_four_calls_contract():
    client = SuperDocsClient(api_key="dummy-superdocs-key")

    # 1. Upload
    sample_txt = "Project Titan Escrow Agreement execution terms."
    upload_res = client.upload_document(sample_txt, filename="escrow_draft.txt")
    assert "document_id" in upload_res
    doc_id = upload_res["document_id"]

    # 2. Chat / Edit Instruction (tests JSON-string double-parse)
    chat_res = client.chat_edit_instruction(
        document_id=doc_id,
        instruction="Verify party signature blocks and check for unexecuted placeholder lines.",
        sample_budget=10,
    )
    assert "proposed_changes" in chat_res
    assert isinstance(chat_res["proposed_changes"], dict)  # Verifies 2nd parse succeeded!
    change_id = chat_res["change_id"]

    # 3. Approve Changes
    approve_res = client.approve_changes(document_id=doc_id, change_id=change_id)
    assert approve_res["status"] == "COMMITTED"

    # 4. Export Deliverable (Exports do not cost operations)
    export_bytes = client.export_deliverable(document_id=doc_id, export_format="pdf")
    assert len(export_bytes) > 0


def test_mcp_server_tools():
    mcp_server = ClosingBinderMCPServer()
    tools = mcp_server.list_tools()

    tool_names = [t["name"] for t in tools]
    assert "assemble_closing_binder" in tool_names
    assert "match_documents_to_checklist" in tool_names
    assert "detect_unsigned_documents" in tool_names
    assert "generate_outstanding_items_report" in tool_names

    # Test MCP tool call: detect_unsigned_documents
    docs_dir = os.path.join(os.path.dirname(__file__), "..", "samples", "executed_documents")
    audit_res = mcp_server.call_tool("detect_unsigned_documents", {"documents_dir": docs_dir})
    assert audit_res["total_audited"] > 0
    assert "documents" in audit_res
