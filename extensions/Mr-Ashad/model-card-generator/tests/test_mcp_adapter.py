"""Tests for SuperDocs MCP Tool Adapter."""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from src.mcp_adapter import SuperDocsMCPAdapter
from src.superdocs_client import SuperDocsClient


def test_mcp_adapter_tool_definitions():
    adapter = SuperDocsMCPAdapter()
    defs = adapter.get_tool_definitions()
    tool_names = [t["name"] for t in defs]

    assert "superdocs_upload" in tool_names
    assert "superdocs_chat" in tool_names
    assert "superdocs_approve" in tool_names
    assert "superdocs_export" in tool_names
    assert "generate_model_card" in tool_names
    assert "refresh_evaluation_tables" in tool_names


def test_mcp_adapter_full_lifecycle():
    client = SuperDocsClient(mock_mode=True)
    adapter = SuperDocsMCPAdapter(client=client)

    # 1. Upload
    upload_res = adapter.call_tool("superdocs_upload", {
        "content": "# Test Model Card\n<!-- EVALUATION_SECTION_START -->\nold\n<!-- EVALUATION_SECTION_END -->",
        "title": "MCP Test Model Card"
    })
    doc_id = upload_res["document_id"]
    assert doc_id is not None

    # 2. Chat
    chat_res = adapter.call_tool("superdocs_chat", {
        "document_id": doc_id,
        "instruction": "Update evaluation",
        "evaluation_markdown": "| Benchmark | Score |\n|---|---|\n| MMLU | 85.0% |"
    })
    assert "diff" in chat_res

    # 3. Approve (with double-json parsed inside)
    approve_res = adapter.call_tool("superdocs_approve", {
        "document_id": doc_id,
        "diff_payload": chat_res
    })
    assert approve_res["status"] == "approved"
    assert approve_res["version"] == 2

    # 4. Export
    export_res = adapter.call_tool("superdocs_export", {
        "document_id": doc_id,
        "formats": ["markdown", "pdf"]
    })
    assert "markdown" in export_res
    assert "| MMLU | 85.0% |" in export_res["markdown"]


def test_mcp_generate_and_refresh_tools(tmp_path):
    manifest = {
        "model_name": "TestMCPModel",
        "version": "1.0.0",
        "intended_purpose": "Testing MCP tool automation",
        "limitations": "None in mock",
        "out_of_scope_uses": "Production deployment without checks",
        "maintenance_contact": "mcp-team@example.com"
    }

    eval_data = {
        "results": [
            {"task_id": "mmlu", "score": 88.5, "baseline_score": 80.0},
            {"task_id": "gsm8k", "score": 92.0, "baseline_score": 85.0}
        ]
    }

    adapter = SuperDocsMCPAdapter(client=SuperDocsClient(mock_mode=True))
    gen_res = adapter.call_tool("generate_model_card", {
        "manifest": manifest,
        "eval_results": eval_data,
        "output_dir": str(tmp_path)
    })

    assert gen_res["version"] == 2

    # Refresh tool test
    card_file = tmp_path / "testmcpmodel.md"
    assert card_file.is_file()

    new_eval_data = {
        "results": [
            {"task_id": "mmlu", "score": 90.0, "baseline_score": 80.0}
        ]
    }

    ref_res = adapter.call_tool("refresh_evaluation_tables", {
        "card_content_or_path": str(card_file),
        "eval_results": new_eval_data
    })

    assert ref_res["status"] == "refreshed"
    assert "90.0%" in card_file.read_text(encoding="utf-8")
