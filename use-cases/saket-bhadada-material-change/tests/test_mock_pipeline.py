import json
import os
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import main_mcp
from main_mcp import run_mcp_pipeline

class TestMockMCPPipeline(unittest.TestCase):

    @patch("main_mcp.sse_client")
    @patch("main_mcp.ClientSession")
    def test_full_pipeline_mock_execution(self, mock_client_session, mock_sse_client):
        # Setup mock session
        session_instance = AsyncMock()
        mock_client_session.return_value.__aenter__.return_value = session_instance
        mock_sse_client.return_value.__aenter__.return_value = (AsyncMock(), AsyncMock())

        # Mock tool list
        mock_tools = MagicMock()
        mock_tools.tools = [
            MagicMock(name="upload"),
            MagicMock(name="chat"),
            MagicMock(name="approve"),
            MagicMock(name="export"),
        ]
        mock_tools.tools[0].name = "upload"
        mock_tools.tools[1].name = "chat"
        mock_tools.tools[2].name = "approve"
        mock_tools.tools[3].name = "export"
        session_instance.list_tools.return_value = mock_tools

        # Setup mock returns for each step
        upload_resp = MagicMock()
        upload_resp.content = [MagicMock(text=json.dumps({"document_id": "doc_101", "status": "uploaded"}))]

        findings_payload = {
            "material_changes": ["Net 60 payment terms", "3x liability cap"],
            "party_favored": "Client",
            "pushback_points": ["Request mutual liability cap", "Maintain Net 30"],
        }
        chat_resp = MagicMock()
        chat_resp.content = [MagicMock(text=json.dumps({"job_id": "job_555", "findings": json.dumps(findings_payload)}))]

        approve_resp = MagicMock()
        approve_resp.content = [MagicMock(text=json.dumps({"status": "approved"}))]

        export_resp = MagicMock()
        export_resp.content = [MagicMock(text="# Final Material Change Analysis Brief\n\n- Net 60\n- 3x Cap")]

        session_instance.call_tool.side_effect = [
            upload_resp,   # v1
            upload_resp,   # v2
            chat_resp,     # chat
            approve_resp,  # approve
            export_resp,   # export
        ]

        v1 = Path(__file__).resolve().parent.parent / "sample_data" / "contract_v1.txt"
        v2 = Path(__file__).resolve().parent.parent / "sample_data" / "contract_v2.txt"

        import asyncio
        with patch.object(main_mcp, "API_KEY", "test_key_123"):
            asyncio.run(run_mcp_pipeline(v1, v2))

        # Verify output file generated
        out_file = Path("final_material_change_brief.md")
        self.assertTrue(out_file.exists())
        content = out_file.read_text(encoding="utf-8")
        self.assertIn("Final Material Change Analysis Brief", content)

if __name__ == "__main__":
    unittest.main()
