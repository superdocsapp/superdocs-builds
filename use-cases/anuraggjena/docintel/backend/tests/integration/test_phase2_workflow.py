"""
Phase 2 integration tests.

These tests verify Phase 2 pipeline components with all DB dependencies mocked.
No real database required — all DB-boundary objects are mocked at creation time.
"""
import pytest
import json
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock


def test_all_phase2_modules_importable():
    """All new Phase 2 modules import without error."""
    from backend.core.retrieval.provider import EmbeddingProvider
    from backend.core.retrieval.sentence_transformer import SentenceTransformerProvider
    from backend.core.retrieval.chunker import DocumentChunker
    from backend.core.retrieval.embedder import Embedder
    from backend.core.retrieval.search import VectorSearchService
    from backend.core.retrieval.citations import CitationBuilder
    from backend.services.retrieval import RetrievalService
    from backend.models.evidence import Evidence, Citation
    from backend.repositories.evidence import EvidenceRepository, CitationRepository
    from backend.api.v1.evidence import router
    from backend.modules.tariff.stages.retrieve import RetrieveStage
    from backend.modules.tariff.stages.citations import CitationBuilderStage
    assert all([
        EmbeddingProvider, SentenceTransformerProvider, DocumentChunker,
        Embedder, VectorSearchService, CitationBuilder, RetrievalService,
        Evidence, Citation, EvidenceRepository, CitationRepository,
        router, RetrieveStage, CitationBuilderStage,
    ])


@pytest.mark.asyncio
async def test_chunker_embedder_retrieve_pipeline_with_mocks():
    """Full pipeline: chunk → embed → search → evidence, all mocked at DB boundary."""
    from backend.core.retrieval.search import SearchResult
    from backend.modules.tariff.stages.retrieve import RetrieveStage
    from backend.modules.tariff.schemas import TariffWorkflowState

    mock_retrieval_svc = AsyncMock()
    mock_retrieval_svc.ingest_document = AsyncMock(return_value=5)
    mock_retrieval_svc.search = AsyncMock(return_value=[
        SearchResult(
            chunk_id=str(uuid4()),
            document_id="doc-1",
            text="HS 8471.30 laptop computers",
            score=0.95,
        ),
        SearchResult(
            chunk_id=str(uuid4()),
            document_id="doc-1",
            text="duty rate 0% for IT products",
            score=0.88,
        ),
    ])

    mock_evidence_repo = AsyncMock()
    mock_evidence_repo.create = AsyncMock(side_effect=lambda **kw: MagicMock(id=uuid4()))

    stage = RetrieveStage(
        retrieval_service=mock_retrieval_svc,
        evidence_repository=mock_evidence_repo,
    )

    state = TariffWorkflowState(
        document_id="doc-1",
        workflow_run_id=str(uuid4()),
        workspace_id=str(uuid4()),
        document_content="Product: laptop computer for business use. HS 8471.30. Duty rate 0%.",
    )

    result = await stage.execute(state)

    assert result["retrieve_completed"] is True
    assert len(result["retrieved_chunks"]) == 2
    assert len(result["evidence_ids"]) == 2
    assert result["retrieved_chunks"][0]["score"] == 0.95


@pytest.mark.asyncio
async def test_generate_then_citations_pipeline():
    """generate_stage persists claims, citations_stage links them to evidence."""
    from backend.modules.tariff.stages.generate import GenerateStage
    from backend.modules.tariff.stages.citations import CitationBuilderStage
    from backend.core.retrieval.citations import CitationBuilder
    from backend.modules.tariff.schemas import TariffWorkflowState, TariffClaim

    # GenerateStage with mock LLM + mock claim repo
    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(return_value=MagicMock(content="The product is classified as HS 8471.30"))
    claim_id = uuid4()
    mock_claim_repo = AsyncMock()
    mock_claim_repo.create = AsyncMock(return_value=MagicMock(id=claim_id))

    gen_stage = GenerateStage(claim_repository=mock_claim_repo)
    gen_stage.llm = mock_llm

    evidence_id = uuid4()
    state = TariffWorkflowState(
        document_id="doc-1",
        workflow_run_id=str(uuid4()),
        workspace_id=str(uuid4()),
        document_content="test",
        extracted_claims=[
            TariffClaim(hs_code="8471.30", description="Laptop", duty_rate="0%"),
        ],
        evidence_ids=[str(evidence_id)],
        retrieved_chunks=[{"chunk_id": "c1", "text": "HS 8471.30 laptop", "score": 0.92}],
    )

    gen_result = await gen_stage.execute(state)
    assert gen_result["generate_completed"] is True
    assert len(gen_result["claim_ids"]) == 1

    # Update state with claim_ids
    state_dict = state.model_dump()
    state_dict.update(gen_result)
    updated_state = TariffWorkflowState(**state_dict)

    # CitationBuilderStage
    mock_citation_repo = AsyncMock()
    mock_citation_repo.create = AsyncMock(return_value=MagicMock(id=uuid4()))
    builder = CitationBuilder(citation_repository=mock_citation_repo)
    cit_stage = CitationBuilderStage(citation_builder=builder)

    cit_result = await cit_stage.execute(updated_state)
    assert cit_result["citations_completed"] is True
    assert len(cit_result["citation_ids"]) >= 1


@pytest.mark.asyncio
async def test_quality_gate_stage_with_mock_state():
    """QualityGateStage.execute() takes a dict — verify pass/fail output keys."""
    from backend.core.quality_gate.stage import QualityGateStage
    from backend.core.quality_gate.checks import BaseCheck, CheckResult, CheckStatus, CheckSeverity

    class AlwaysPassCheck(BaseCheck):
        name = "always_pass"
        severity = CheckSeverity.WARNING
        blocking = False

        async def run(self, state, config):
            return CheckResult(
                check_name=self.name,
                status=CheckStatus.PASSED,
                severity=self.severity,
                message="All good",
                blocking=False,
            )

    stage = QualityGateStage(checks=[AlwaysPassCheck()])

    state = {
        "workspace_id": str(uuid4()),
        "workflow_run_id": str(uuid4()),
        "extracted_claims": [{"hs_code": "8471.30"}],
        "generated_report": "Some report content",
    }

    result = await stage.execute(state)

    assert "quality_gate_status" in result
    assert "quality_gate_details" in result
    assert result["quality_gate_status"] in ("passed", "failed", "warning", "skipped")


@pytest.mark.asyncio
async def test_knowledge_retrieve_stage_with_mock_engine():
    """KnowledgeRetrieveStage.execute() takes a dict — verify output keys."""
    from backend.core.knowledge.stages import KnowledgeRetrieveStage

    mock_engine = AsyncMock()
    mock_engine.retrieve_as_context = AsyncMock(return_value="Prior tariff classification context.")
    mock_entry = MagicMock()
    mock_entry.id = uuid4()
    mock_engine.retrieve = AsyncMock(return_value=[mock_entry])

    stage = KnowledgeRetrieveStage(engine=mock_engine, workflow_type="tariff")

    state = {
        "workspace_id": str(uuid4()),
        "workflow_run_id": str(uuid4()),
        "tags": ["tariff", "hs_code"],
    }

    result = await stage.execute(state)

    assert "prior_knowledge" in result
    assert "prior_knowledge_entries" in result
    assert result["prior_knowledge"] == "Prior tariff classification context."
    assert len(result["prior_knowledge_entries"]) == 1


@pytest.mark.asyncio
async def test_knowledge_store_stage_with_mock_engine():
    """KnowledgeStoreStage.execute() takes a dict — verify stored count."""
    from backend.core.knowledge.stages import KnowledgeStoreStage

    mock_engine = AsyncMock()
    mock_engine.store = AsyncMock(return_value=MagicMock(id=uuid4()))

    stage = KnowledgeStoreStage(engine=mock_engine, workflow_type="tariff")

    state = {
        "workspace_id": str(uuid4()),
        "workflow_run_id": str(uuid4()),
        "document_id": "doc-1",
        "claims": [
            {"content": "HS 8471.30 applies to laptops", "confidence_score": 0.9, "tags": ["tariff"]},
        ],
        "generated_output": "Classification report: HS 8471.30",
    }

    result = await stage.execute(state)

    assert "knowledge_stored" in result
    assert result["knowledge_stored"] == 2  # 1 claim + 1 summary


@pytest.mark.asyncio
async def test_full_7_stage_pipeline_all_mocked():
    """
    Full 7-stage pipeline in order:
      1. KnowledgeRetrieveStage (dict)
      2. ExtractStage (TariffWorkflowState) — LLM mocked
      3. RetrieveStage (TariffWorkflowState) — retrieval + evidence repo mocked
      4. GenerateStage (TariffWorkflowState) — LLM + claim repo mocked
      5. CitationBuilderStage (TariffWorkflowState) — citation repo mocked
      6. QualityGateStage (dict)
      7. KnowledgeStoreStage (dict)
    """
    from backend.core.knowledge.stages import KnowledgeRetrieveStage, KnowledgeStoreStage
    from backend.modules.tariff.stages.extract import ExtractStage
    from backend.modules.tariff.stages.retrieve import RetrieveStage
    from backend.modules.tariff.stages.generate import GenerateStage
    from backend.modules.tariff.stages.citations import CitationBuilderStage
    from backend.core.retrieval.citations import CitationBuilder
    from backend.core.quality_gate.stage import QualityGateStage
    from backend.core.quality_gate.checks import BaseCheck, CheckResult, CheckStatus, CheckSeverity
    from backend.core.retrieval.search import SearchResult
    from backend.modules.tariff.schemas import TariffWorkflowState, TariffClaim

    workspace_id = str(uuid4())
    workflow_run_id = str(uuid4())
    document_id = "doc-pipeline-test"

    # --- Stage 1: KnowledgeRetrieveStage ---
    mock_k_engine = AsyncMock()
    mock_k_engine.retrieve_as_context = AsyncMock(return_value="Prior knowledge context.")
    mock_k_entry = MagicMock()
    mock_k_entry.id = uuid4()
    mock_k_engine.retrieve = AsyncMock(return_value=[mock_k_entry])
    mock_k_engine.store = AsyncMock(return_value=MagicMock(id=uuid4()))

    k_retrieve_stage = KnowledgeRetrieveStage(engine=mock_k_engine, workflow_type="tariff")

    state_dict = {
        "workspace_id": workspace_id,
        "workflow_run_id": workflow_run_id,
        "document_id": document_id,
        "tags": [],
    }
    k_result = await k_retrieve_stage.execute(state_dict)
    assert "prior_knowledge" in k_result

    # --- Build TariffWorkflowState for tariff-specific stages ---
    state = TariffWorkflowState(
        document_id=document_id,
        workflow_run_id=workflow_run_id,
        workspace_id=workspace_id,
        document_content="Laptop computers for business use. HS 8471.30. Duty rate 0%.",
        prior_knowledge=k_result["prior_knowledge"],
        prior_knowledge_entries=k_result["prior_knowledge_entries"],
    )

    # --- Stage 2: ExtractStage (LLM mocked) ---
    extract_stage = ExtractStage()
    mock_llm_extract = AsyncMock()
    mock_llm_extract.generate_structured = AsyncMock(
        return_value=MagicMock(
            claims=[TariffClaim(hs_code="8471.30", description="Laptop", duty_rate="0%")]
        )
    )
    extract_stage.llm = mock_llm_extract

    extract_result = await extract_stage.execute(state)
    assert extract_result["extract_completed"] is True
    state_dict2 = state.model_dump()
    state_dict2.update(extract_result)
    state = TariffWorkflowState(**state_dict2)

    # --- Stage 3: RetrieveStage ---
    mock_retrieval_svc = AsyncMock()
    mock_retrieval_svc.ingest_document = AsyncMock(return_value=3)
    mock_retrieval_svc.search = AsyncMock(return_value=[
        SearchResult(chunk_id=str(uuid4()), document_id=document_id, text="HS 8471.30 laptops", score=0.93),
    ])
    mock_evidence_repo = AsyncMock()
    evidence_id = uuid4()
    mock_evidence_repo.create = AsyncMock(return_value=MagicMock(id=evidence_id))

    retrieve_stage = RetrieveStage(
        retrieval_service=mock_retrieval_svc,
        evidence_repository=mock_evidence_repo,
    )
    retrieve_result = await retrieve_stage.execute(state)
    assert retrieve_result["retrieve_completed"] is True
    state_dict3 = state.model_dump()
    state_dict3.update(retrieve_result)
    state = TariffWorkflowState(**state_dict3)

    # --- Stage 4: GenerateStage ---
    mock_llm_gen = AsyncMock()
    mock_llm_gen.generate = AsyncMock(return_value=MagicMock(content="Classification: HS 8471.30"))
    mock_claim_repo = AsyncMock()
    claim_id = uuid4()
    mock_claim_repo.create = AsyncMock(return_value=MagicMock(id=claim_id))

    gen_stage = GenerateStage(claim_repository=mock_claim_repo)
    gen_stage.llm = mock_llm_gen

    gen_result = await gen_stage.execute(state)
    assert gen_result["generate_completed"] is True
    state_dict4 = state.model_dump()
    state_dict4.update(gen_result)
    state = TariffWorkflowState(**state_dict4)

    # --- Stage 5: CitationBuilderStage ---
    mock_citation_repo = AsyncMock()
    mock_citation_repo.create = AsyncMock(return_value=MagicMock(id=uuid4()))
    builder = CitationBuilder(citation_repository=mock_citation_repo)
    cit_stage = CitationBuilderStage(citation_builder=builder)

    cit_result = await cit_stage.execute(state)
    assert cit_result["citations_completed"] is True
    state_dict5 = state.model_dump()
    state_dict5.update(cit_result)
    state = TariffWorkflowState(**state_dict5)

    # --- Stage 6: QualityGateStage (takes dict) ---
    class AlwaysPassCheck(BaseCheck):
        name = "always_pass"
        severity = CheckSeverity.INFO
        blocking = False

        async def run(self, state, config):
            return CheckResult(
                check_name=self.name,
                status=CheckStatus.PASSED,
                severity=self.severity,
                message="Passed",
                blocking=False,
            )

    qg_stage = QualityGateStage(checks=[AlwaysPassCheck()])
    qg_state_dict = state.model_dump()
    # model_dump may serialize UUIDs — ensure strings
    qg_state_dict["workspace_id"] = str(qg_state_dict.get("workspace_id", workspace_id))
    qg_state_dict["workflow_run_id"] = str(qg_state_dict.get("workflow_run_id", workflow_run_id))

    qg_result = await qg_stage.execute(qg_state_dict)
    assert "quality_gate_status" in qg_result
    state_dict6 = state.model_dump()
    state_dict6.update(qg_result)
    state = TariffWorkflowState(**state_dict6)

    # --- Stage 7: KnowledgeStoreStage (takes dict) ---
    k_store_stage = KnowledgeStoreStage(
        engine=mock_k_engine,
        workflow_type="tariff",
        claims_key="extracted_claims",
        output_key="generated_report",
    )
    store_state_dict = state.model_dump()
    store_state_dict["workspace_id"] = workspace_id
    store_state_dict["workflow_run_id"] = workflow_run_id
    # Convert TariffClaim objects to dicts for KnowledgeStoreStage
    store_state_dict["extracted_claims"] = [
        {"content": f"{c['hs_code']}: {c['description']}", "confidence_score": None, "tags": []}
        if isinstance(c, dict) else
        {"content": f"{c.hs_code}: {c.description}", "confidence_score": None, "tags": []}
        for c in state.extracted_claims
    ]

    store_result = await k_store_stage.execute(store_state_dict)
    assert "knowledge_stored" in store_result
    # 1 claim stored + 1 generated_report = 2
    assert store_result["knowledge_stored"] >= 1
