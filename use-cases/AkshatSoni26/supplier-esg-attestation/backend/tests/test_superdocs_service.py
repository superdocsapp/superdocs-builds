import json
import pytest
from app.schemas.superdocs import (
    SuperDocsChatRequest,
    SuperDocsChatResponse,
    SuperDocsApproveRequest,
)
from app.services.superdocs_service import SuperDocsClientService


@pytest.mark.asyncio
async def test_superdocs_4_step_contract_mock():
    """Verify upload -> chat -> approve -> export executes without error in mock/test mode."""
    service = SuperDocsClientService()

    # Step 1: Upload
    upload_res = await service.upload_document(
        filename="test_attestation.md",
        content="# Test Supplier Attestation\n\nContent for testing."
    )
    assert upload_res.document_id.startswith("sd-doc-")
    assert upload_res.filename == "test_attestation.md"

    # Step 2: Chat / Edit Instruction
    chat_res = await service.send_chat_instruction(SuperDocsChatRequest(
        document_id=upload_res.document_id,
        instruction="Verify compliance clauses and flag discrepancies."
    ))
    assert chat_res.status == "awaiting_approval"
    assert len(chat_res.parsed_diffs) > 0

    # Step 3: Approve
    approve_ok = await service.approve_changes(SuperDocsApproveRequest(
        document_id=upload_res.document_id,
        approved_diff_ids=[chat_res.parsed_diffs[0].diff_id],
        rejected_diff_ids=[]
    ))
    assert approve_ok is True

    # Step 4: Export
    export_res = await service.export_document(upload_res.document_id, format_type="pdf")
    assert export_res.document_id == upload_res.document_id
    assert export_res.export_format == "pdf"
    assert export_res.download_url.endswith(".pdf")


def test_superdocs_two_step_json_string_parsing():
    """Verify that double JSON string encoding from SuperDocs is parsed correctly."""
    inner_diffs = [
        {
            "diff_id": "diff-test-99",
            "target_section": "GHG Scope 2",
            "original_text": "Not tracked.",
            "suggested_text": "Require certified audit.",
            "rationale": "Mandatory tier 1 requirement."
        }
    ]
    # Simulate double JSON string
    double_encoded = json.dumps(json.dumps(inner_diffs))
    
    parsed = SuperDocsChatResponse.parse_raw_changes(double_encoded)
    assert len(parsed) == 1
    assert parsed[0].diff_id == "diff-test-99"
    assert parsed[0].target_section == "GHG Scope 2"
    assert parsed[0].original_text == "Not tracked."
