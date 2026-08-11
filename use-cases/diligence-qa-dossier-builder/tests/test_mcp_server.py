import pytest
import base64
import uuid
import json
from unittest.mock import patch, AsyncMock, MagicMock
from sqlalchemy import select

import mcp.types as types
from backend.app.models import Dossier, DossierFinding, Document, DocumentChunk
from backend.app.services.llm import MockLLMService, LLMResponse
from tests.test_integration import AsyncTestSession
from mcp_server import handle_list_tools, handle_call_tool

def test_mcp_server_features():
    """
    Integration test suite verifying the MCP server's tool discovery, 
    tool executions, error validation, and isolation capabilities.
    """
    with AsyncTestSession() as ts:
        # Verify 1: Tool Discovery
        res_list = ts.run(handle_list_tools(None))
        tools = res_list.tools
        assert len(tools) == 4
        tool_names = {t.name for t in tools}
        assert tool_names == {
            "upload_document",
            "send_edit_instruction",
            "approve_proposed_changes",
            "export_result"
        }

        # Verify 2: upload_document (Success & Duplicate Handling)
        sample_text = b"Acme post-merger compliance structure details."
        base64_payload = base64.b64encode(sample_text).decode("utf-8")
        
        with patch("mcp_server.AsyncSessionLocal", return_value=ts.session):
            # Normal upload
            resp = ts.run(handle_call_tool(types.CallToolRequestParams(
                name="upload_document",
                arguments={
                    "filename": "mcp_compliance.txt",
                    "content_base64": base64_payload
                }
            )))
            assert len(resp.content) == 1
            data = json.loads(resp.content[0].text)
            assert data["ingestion_status"] == "success"
            doc_id = data["document_id"]
            assert doc_id is not None
            assert data["filename"] == "mcp_compliance.txt"
            
            # Duplicate document upload
            resp_dup = ts.run(handle_call_tool(types.CallToolRequestParams(
                name="upload_document",
                arguments={
                    "filename": "mcp_compliance_dup.txt",
                    "content_base64": base64_payload
                }
            )))
            assert len(resp_dup.content) == 1
            data_dup = json.loads(resp_dup.content[0].text)
            assert data_dup["ingestion_status"] == "duplicate"
            assert data_dup["duplicate_status"] is True
            assert "Duplicate document detected" in data_dup["error"]

            # Unsupported file extension check
            resp_bad = ts.run(handle_call_tool(types.CallToolRequestParams(
                name="upload_document",
                arguments={
                    "filename": "mcp_unsupported.exe",
                    "content_base64": base64_payload
                }
            )))
            assert len(resp_bad.content) == 1
            data_bad = json.loads(resp_bad.content[0].text)
            assert "Unsupported file type" in data_bad["message"]

        # Prepare a dossier and findings to verify send_edit_instruction, approve_proposed_changes, and export_result
        async def prepare_test_dossiers():
            async with ts.SessionLocal() as session:
                # Dossier A
                da = Dossier(name="MCP Target Dossier A", status="pending")
                session.add(da)
                await session.flush()
                
                fa1 = DossierFinding(
                    dossier_id=da.id,
                    question="What is target compliance posture?",
                    status="answered",
                    review_status="pending",
                    workflow_thread_id=str(uuid.uuid4()),
                    confidence=0.50,
                    answer="Semi-completed compliance.",
                    reasoning_summary="Found partial docs.",
                    citations=[]
                )
                fa2 = DossierFinding(
                    dossier_id=da.id,
                    question="What is ARR?",
                    status="insufficient_evidence",
                    review_status="not_required",
                    workflow_thread_id=str(uuid.uuid4()),
                    confidence=0.0,
                    answer="",
                    reasoning_summary="No docs found.",
                    citations=[]
                )
                session.add_all([fa1, fa2])

                # Dossier B (for leakage / mismatch checks)
                db = Dossier(name="MCP Isolated Dossier B", status="pending")
                session.add(db)
                await session.flush()
                
                fb1 = DossierFinding(
                    dossier_id=db.id,
                    question="Beta secret sauce?",
                    status="answered",
                    review_status="pending",
                    workflow_thread_id=str(uuid.uuid4()),
                    confidence=0.85,
                    answer="Secret recipe.",
                    reasoning_summary="Recipe text.",
                    citations=[]
                )
                session.add(fb1)
                
                await session.commit()
                return str(da.id), str(fa1.id), str(fa2.id), str(db.id), str(fb1.id)

        da_id, fa1_id, fa2_id, db_id, fb1_id = ts.run(prepare_test_dossiers())

        with patch("mcp_server.AsyncSessionLocal", return_value=ts.session):
            # Verify 3: send_edit_instruction (Validation, Mismatch & Success)
            # Dossier / Finding ID mismatch check
            resp_mismatch = ts.run(handle_call_tool(types.CallToolRequestParams(
                name="send_edit_instruction",
                arguments={
                    "dossier_id": da_id,
                    "finding_id": fb1_id,  # belongs to B
                    "answer": "Modified answer.",
                    "reasoning_summary": "Notes."
                }
            )))
            assert "Finding not found in the requested dossier" in json.loads(resp_mismatch.content[0].text)["message"]

            # Invalid UUID format check
            resp_invalid = ts.run(handle_call_tool(types.CallToolRequestParams(
                name="send_edit_instruction",
                arguments={
                    "dossier_id": "bad-id",
                    "finding_id": fa1_id,
                    "answer": "Answer.",
                    "reasoning_summary": "Notes."
                }
            )))
            assert "Invalid UUID format" in json.loads(resp_invalid.content[0].text)["message"]

            # Successful send_edit_instruction
            with patch("mcp_server.compile_diligence_workflow") as mock_workflow:
                mock_graph = MagicMock()
                mock_graph.aupdate_state = AsyncMock()
                mock_graph.ainvoke = AsyncMock()
                mock_workflow.return_value = mock_graph

                resp_edit = ts.run(handle_call_tool(types.CallToolRequestParams(
                    name="send_edit_instruction",
                    arguments={
                        "dossier_id": da_id,
                        "finding_id": fa1_id,
                        "answer": "Grounded compliance posture is SOC2 compliant.",
                        "reasoning_summary": "Reviewed updated documentation."
                    }
                )))
                assert len(resp_edit.content) == 1
                data_edit = json.loads(resp_edit.content[0].text)
                assert data_edit["finding_id"] == fa1_id
                assert data_edit["status"] == "answered"
                assert data_edit["review_status"] == "edited"
                assert data_edit["answer"] == "Grounded compliance posture is SOC2 compliant."

            # Verify 4: approve_proposed_changes (Already reviewed check & Success)
            # Call approve on fa1 which is now "edited"
            resp_app_invalid = ts.run(handle_call_tool(types.CallToolRequestParams(
                name="approve_proposed_changes",
                arguments={
                    "dossier_id": da_id,
                    "finding_id": fa1_id
                }
            )))
            assert "Finding is not awaiting review" in json.loads(resp_app_invalid.content[0].text)["message"]

            # Approve fb1 (which is pending review)
            with patch("mcp_server.compile_diligence_workflow") as mock_workflow:
                mock_graph = MagicMock()
                mock_graph.aupdate_state = AsyncMock()
                mock_graph.ainvoke = AsyncMock()
                mock_workflow.return_value = mock_graph

                resp_app = ts.run(handle_call_tool(types.CallToolRequestParams(
                    name="approve_proposed_changes",
                    arguments={
                        "dossier_id": db_id,
                        "finding_id": fb1_id
                    }
                )))
                assert len(resp_app.content) == 1
                data_app = json.loads(resp_app.content[0].text)
                assert data_app["finding_id"] == fb1_id
                assert data_app["review_status"] == "approved"
                assert data_app["status"] == "answered"

            # Verify 5: export_result (Markdown formatting & Leakage isolation)
            resp_exp = ts.run(handle_call_tool(types.CallToolRequestParams(
                name="export_result",
                arguments={"dossier_id": da_id}
            )))
            assert len(resp_exp.content) == 1
            md_text = resp_exp.content[0].text
            
            # Formatting checks
            assert "# Diligence Dossier Report: MCP Target Dossier A" in md_text
            assert "What is target compliance posture?" in md_text
            assert "Grounded compliance posture is SOC2 compliant." in md_text
            assert "Workflow Status**: ANSWERED" in md_text
            assert "Unresolved Diligence Gap" in md_text
            assert "Evidence was not found in the data room documents." in md_text

            # Cross-dossier export isolation checks
            assert "MCP Isolated Dossier B" not in md_text
            assert "Beta secret sauce" not in md_text
            assert "Secret recipe." not in md_text
            assert fb1_id not in md_text

            # Non-existent dossier export check
            fake_d_id = str(uuid.uuid4())
            resp_exp_bad = ts.run(handle_call_tool(types.CallToolRequestParams(
                name="export_result",
                arguments={"dossier_id": fake_d_id}
            )))
            assert "Dossier not found" in json.loads(resp_exp_bad.content[0].text)["message"]
