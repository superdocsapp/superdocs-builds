"""
Regression tests for Tariff export wiring and auto-download artifact resolution.

Verifies:
1. Completed Tariff run auto-export produces the canonical Tariff Classification Memo DOCX.
2. The generated DOCX is NOT the original product specification document.
3. Original source documents in storage remain untouched/unmodified.
4. DOCX and PDF export endpoints generate the same canonical content model.
5. Dynamic filename convention resolves properly from the source document (e.g. AeroLink_X7_Tariff_Classification.docx).
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4
from io import BytesIO
from docx import Document

from backend.modules.tariff.stages.superdocs_export import SuperDocsExportStage
from backend.modules.tariff.schemas import TariffWorkflowState
from backend.services.export import ExportService
from backend.models.export import Export
from backend.models.workflow import WorkflowRun
from backend.models.workspace import Workspace
from backend.models.document import Document as DocumentModel
from backend.models.memo_section import MemoSection


@pytest.fixture
def original_spec_bytes():
    """Simulate raw uploaded product specification DOCX bytes."""
    return b"PK\x03\x04--RAW-ORIGINAL-PRODUCT-SPEC-AEROLINK-X7--"


@pytest.fixture
def mock_tariff_environment(original_spec_bytes):
    workspace_id = uuid4()
    run_id = uuid4()
    doc_id = uuid4()

    workspace = MagicMock(spec=Workspace)
    workspace.id = workspace_id
    workspace.name = "AeroLink Workspace"

    run = MagicMock(spec=WorkflowRun)
    run.id = run_id
    run.status = "completed"
    run.workflow_version = "1.0.0"

    source_doc = MagicMock(spec=DocumentModel)
    source_doc.id = doc_id
    source_doc.workspace_id = workspace_id
    source_doc.filename = "AEROLINK X7.docx"
    source_doc.document_role = "product_spec"
    source_doc.storage_path = f"{workspace_id}/AEROLINK X7.docx"

    sections = [
        MagicMock(
            spec=MemoSection,
            title="Executive Summary",
            section_order=1,
            section_type="executive_summary",
            content="Executive summary: AeroLink X7 is classified under 8806.22.0000.",
            analyst_reasoning="Classification reasoning for executive summary.",
            source_attribution=[{"document_id": str(doc_id), "page": 1, "excerpt": "Drone spec"}],
            structured_data=None,
            status="completed",
        ),
        MagicMock(
            spec=MemoSection,
            title="Recommended Classification",
            section_order=2,
            section_type="recommended_classification",
            content="Recommended classification under HS 8806.22.0000.",
            analyst_reasoning="Applied GRI 1 and Note 1 to Chapter 88.",
            source_attribution=[],
            structured_data={
                "recommendation": {
                    "hs_code": "8806.22.0000",
                    "description": "Unmanned aircraft: Other, with maximum takeoff weight more than 250 g but not more than 7 kg",
                    "reasoning": "AeroLink X7 weight of 1.2 kg falls strictly in this bracket.",
                    "duty_rate": "Free",
                }
            },
            status="completed",
        ),
        MagicMock(
            spec=MemoSection,
            title="Product Description",
            section_order=3,
            section_type="product_description",
            content="The AeroLink X7 is a high-performance commercial quadcopter UAV.",
            analyst_reasoning="Extracted from manufacturer spec.",
            source_attribution=[{"document_id": str(doc_id), "page": 2, "excerpt": "Quadcopter UAV"}],
            structured_data=None,
            status="completed",
        ),
        MagicMock(
            spec=MemoSection,
            title="Technical Characteristics",
            section_order=4,
            section_type="technical_characteristics",
            content="Max takeoff weight: 1.2 kg. 4K camera payload. 30-minute flight time.",
            analyst_reasoning="Technical data analysis.",
            source_attribution=[],
            structured_data=None,
            status="completed",
        ),
        MagicMock(
            spec=MemoSection,
            title="Classification Rules & Analysis",
            section_order=5,
            section_type="classification_rules",
            content="GRI 1 governs classification according to the terms of headings.",
            analyst_reasoning="Legal analysis under General Rules of Interpretation.",
            source_attribution=[],
            structured_data=None,
            status="completed",
        ),
        MagicMock(
            spec=MemoSection,
            title="Alternatives Considered & Rejected",
            section_order=6,
            section_type="alternatives_considered",
            content="Heading 8525 was considered for camera transmission but rejected under GRI 1.",
            analyst_reasoning="Alternative rejection rationale.",
            source_attribution=[],
            structured_data=None,
            status="completed",
        ),
        MagicMock(
            spec=MemoSection,
            title="Supporting Citations",
            section_order=7,
            section_type="supporting_citations",
            content="Cross-reference CBP Rulings HQ H301234 and NY N305678.",
            analyst_reasoning="Precedent ruling alignment.",
            source_attribution=[{"document_id": str(doc_id), "page": 4, "excerpt": "Precedent CBP NY N305678"}],
            structured_data=None,
            status="completed",
        ),
        MagicMock(
            spec=MemoSection,
            title="Final Recommendation",
            section_order=8,
            section_type="final_recommendation",
            content="Final recommendation: Import under 8806.22.0000 with 0% duty.",
            analyst_reasoning="Final conclusion.",
            source_attribution=[],
            structured_data=None,
            status="completed",
        ),
    ]

    run_repo = AsyncMock()
    run_repo.get_by_id = AsyncMock(return_value=run)

    workspace_repo = AsyncMock()
    workspace_repo.get_by_id = AsyncMock(return_value=workspace)

    doc_repo = AsyncMock()
    doc_repo.get_by_id = AsyncMock(return_value=source_doc)
    doc_repo.list_by_workspace = AsyncMock(return_value=[source_doc])

    memo_section_repo = AsyncMock()
    memo_section_repo.list_by_run = AsyncMock(return_value=sections)

    storage_dict = {
        source_doc.storage_path: original_spec_bytes,
    }

    class MockStorage:
        def __init__(self):
            self.saved_files = {}

        def save(self, data: bytes, filename: str, workspace_id_str: str) -> str:
            path = f"{workspace_id_str}/{filename}"
            self.saved_files[path] = data
            storage_dict[path] = data
            return path

        def read(self, path: str) -> bytes:
            return storage_dict.get(path, b"")

    storage = MockStorage()

    export_repo = AsyncMock()
    async def create_export(**kwargs):
        exp = MagicMock(spec=Export)
        exp.id = uuid4()
        exp.workspace_id = kwargs["workspace_id"]
        exp.workflow_run_id = kwargs["workflow_run_id"]
        exp.filename = kwargs["filename"]
        exp.format = kwargs["format"]
        exp.storage_path = kwargs["storage_path"]
        exp.file_size = kwargs["file_size"]
        return exp
    export_repo.create = AsyncMock(side_effect=create_export)

    export_service = ExportService(
        export_repository=export_repo,
        review_repository=AsyncMock(),
        claim_repository=AsyncMock(),
        workspace_repository=workspace_repo,
        document_repository=doc_repo,
        run_repository=run_repo,
        stage_repository=AsyncMock(),
        storage=storage,
        memo_section_repository=memo_section_repo,
    )

    return {
        "workspace_id": workspace_id,
        "run_id": run_id,
        "source_doc": source_doc,
        "original_spec_bytes": original_spec_bytes,
        "export_service": export_service,
        "storage": storage,
        "storage_dict": storage_dict,
    }


@pytest.mark.asyncio
async def test_superdocs_export_stage_generates_canonical_tariff_memo(mock_tariff_environment):
    env = mock_tariff_environment
    stage = SuperDocsExportStage(export_service=env["export_service"])

    state = TariffWorkflowState(
        workflow_run_id=str(env["run_id"]),
        workspace_id=str(env["workspace_id"]),
        superdocs_session_id="sess-xyz",
        superdocs_approval_completed=True,
    )

    result = await stage.execute(state)
    assert result["export_completed"] is True
    assert "export_id" in result

    saved_paths = list(env["storage"].saved_files.keys())
    assert len(saved_paths) == 1
    saved_path = saved_paths[0]

    assert "AEROLINK_X7_Tariff_Classification.docx" in saved_path

    generated_bytes = env["storage"].read(saved_path)

    # 1. Verify generated DOCX bytes are NOT equal to raw product spec
    assert generated_bytes != env["original_spec_bytes"]

    # 2. Verify original product spec remains unaltered
    assert env["storage_dict"][env["source_doc"].storage_path] == env["original_spec_bytes"]

    # 3. Verify generated DOCX structure and sections
    doc = Document(BytesIO(generated_bytes))
    full_text = "\n".join(p.text for p in doc.paragraphs)

    assert "Tariff Classification Memo" in full_text
    assert "AEROLINK X7.docx" in full_text
    assert "Executive Summary" in full_text
    assert "8806.22.0000" in full_text
    assert "Recommended Classification" in full_text
    assert "Product Description" in full_text
    assert "Technical Characteristics" in full_text
    assert "Classification Rules & Analysis" in full_text
    assert "Alternatives Considered & Rejected" in full_text
    assert "Supporting Citations" in full_text
    assert "Final Recommendation" in full_text


@pytest.mark.asyncio
async def test_manual_docx_and_pdf_export_parity(mock_tariff_environment):
    env = mock_tariff_environment
    service = env["export_service"]

    # Export DOCX
    docx_export = await service.export_run_as_docx(
        run_id=env["run_id"],
        workspace_id=env["workspace_id"],
    )
    assert docx_export.filename == "AEROLINK_X7_Tariff_Classification.docx"
    assert docx_export.format == "docx"

    # Export PDF
    pdf_export = await service.export_run_as_pdf(
        run_id=env["run_id"],
        workspace_id=env["workspace_id"],
    )
    assert pdf_export.filename == "AEROLINK_X7_Tariff_Classification.pdf"
    assert pdf_export.format == "pdf"

    docx_bytes = env["storage"].read(docx_export.storage_path)
    pdf_bytes = env["storage"].read(pdf_export.storage_path)

    assert len(docx_bytes) > 0
    assert len(pdf_bytes) > 0
    assert pdf_bytes.startswith(b"%PDF")

    docx_doc = Document(BytesIO(docx_bytes))
    docx_text = "\n".join(p.text for p in docx_doc.paragraphs)
    assert "8806.22.0000" in docx_text
    assert "Tariff Classification Memo" in docx_text
