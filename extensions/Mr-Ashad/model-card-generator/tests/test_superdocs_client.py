"""Tests for SuperDocs 4-Call Client, Polling, and Error Handlers."""

import time
import pytest
from pathlib import Path
from src.superdocs_client import (
    SuperDocsClient,
    SuperDocsAPIError,
    ExportPollingTimeoutError,
)


def test_complete_four_call_lifecycle(tmp_path):
    """Test full 4-call flow: Upload -> Chat -> Approve -> Export."""
    client = SuperDocsClient(mock_mode=True)
    initial_content = (
        "# Model Card: TestModel\n"
        "<!-- EVALUATION_TIMESTAMP_START -->\n"
        "- **Last Updated**: 2026-08-01\n"
        "<!-- EVALUATION_TIMESTAMP_END -->\n"
        "<!-- EVALUATION_SECTION_START -->\n"
        "| Benchmark | Score |\n"
        "| MMLU | 70% |\n"
        "<!-- EVALUATION_SECTION_END -->\n"
    )

    # 1. Upload
    up_res = client.upload(content=initial_content, title="Test Model Card")
    assert "document_id" in up_res
    doc_id = up_res["document_id"]
    assert up_res["status"] == "created"

    # 2. Chat
    chat_res = client.chat(
        document_id=doc_id,
        instruction="Update evaluation table with latest results",
        evaluation_markdown="| Benchmark | Score |\n| MMLU | 92.5% |",
        timestamp="2026-08-17 12:00:00 UTC",
        run_id="run-test-4call",
    )
    assert "diff" in chat_res
    assert chat_res["status"] == "diff_proposed"

    # 3. Approve (with double JSON parse)
    app_res = client.approve(document_id=doc_id, chat_response_or_diff=chat_res)
    assert app_res["status"] == "approved"
    assert app_res["version"] == 2

    # 4. Export (Markdown + PDF)
    export_res = client.export(
        document_id=doc_id,
        output_dir=tmp_path,
        base_filename="test_card_out"
    )

    assert "markdown" in export_res
    assert "pdf" in export_res
    assert "92.5%" in export_res["markdown"]
    assert Path(export_res["markdown_path"]).is_file()
    assert Path(export_res["pdf_path"]).is_file()

    # Validate PDF signature
    pdf_bytes = Path(export_res["pdf_path"]).read_bytes()
    assert pdf_bytes.startswith(b"%PDF-1.4")


def test_polling_timeout_guardrail():
    """Verify that export polling raises ExportPollingTimeoutError when total timeout is exceeded."""
    client = SuperDocsClient(mock_mode=False, base_url="http://mock-endpoint.invalid")
    
    # Simulate polling timeout with very short timeout budget
    with pytest.raises(ExportPollingTimeoutError):
        client._poll_export_task(
            task_id="task_timeout_test",
            initial_delay=0.01,
            backoff_factor=1.1,
            max_delay=0.05,
            max_retries=3,
            total_timeout_sec=0.02
        )
