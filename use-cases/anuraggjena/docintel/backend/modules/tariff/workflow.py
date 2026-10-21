from backend.core.workflow.registry import workflow_registry
from backend.core.workflow.stage import StageNode
from backend.modules.tariff.stages import (
    ExtractStage,
    GenerateStage,
    RetrieveStage,
    CitationBuilderStage,
    ExtractProductFactsStage,
    ExtractRulingFactsStage,
    GenerateMemoSectionsStage,
)
from backend.modules.tariff.stages.discover_documents import DiscoverDocumentsStage
from backend.modules.tariff.stages.load_product_content import LoadProductContentStage
from backend.modules.tariff.stages.load_ruling_content import LoadRulingContentStage
from backend.modules.tariff.stages.reconcile_documents import ReconcileDocumentsStage
from backend.modules.tariff.stages.superdocs_approval import SuperDocsApprovalStage
from backend.modules.tariff.stages.superdocs_upload import SuperDocsUploadStage
from backend.modules.tariff.stages.superdocs_instruction import SuperDocsInstructionStage
from backend.modules.tariff.stages.superdocs_export import SuperDocsExportStage
from backend.modules.tariff.schemas import TariffWorkflowState
from backend.logging_config import get_logger
from backend.config import settings

logger = get_logger(__name__)


def build_tariff_stages(db_session=None):
    """
    Build tariff workflow stage instances.

    When db_session is provided, returns the full memo pipeline with all
    dependencies wired to the DB session.
    When db_session is None, returns minimal stub list for registry validation.
    """
    extract_stage = ExtractStage()
    generate_stage = GenerateStage(claim_repository=None)

    if db_session is not None:
        from backend.core.retrieval.sentence_transformer import SentenceTransformerProvider
        from backend.core.retrieval.chunker import DocumentChunker
        from backend.core.retrieval.embedder import Embedder
        from backend.core.retrieval.search import VectorSearchService
        from backend.core.retrieval.citations import CitationBuilder
        from backend.services.retrieval import RetrievalService
        from backend.repositories.evidence import EvidenceRepository, CitationRepository
        from backend.core.knowledge.engine import KnowledgeEngine
        from backend.core.knowledge.stages import KnowledgeRetrieveStage, KnowledgeStoreStage
        from backend.core.quality_gate.stage import QualityGateStage
        from backend.repositories.lineage import LineageLinkRepository
        from backend.repositories.memo_section import MemoSectionRepository
        from backend.services.memo_section import MemoSectionService

        provider = SentenceTransformerProvider()
        chunker = DocumentChunker(chunk_size=512, chunk_overlap=64)
        embedder = Embedder(provider=provider, session=db_session)
        search_svc = VectorSearchService(session=db_session)
        retrieval_svc = RetrievalService(chunker=chunker, embedder=embedder, search=search_svc)
        evidence_repo = EvidenceRepository(db_session)
        citation_repo = CitationRepository(db_session)
        claim_repo = _make_claim_repo(db_session)
        lineage_link_repo = LineageLinkRepository(db_session)
        memo_section_repo = MemoSectionRepository(db_session)
        memo_section_service = MemoSectionService(memo_section_repo, claim_repo)

        extract_product_facts_stage = ExtractProductFactsStage()
        extract_ruling_facts_stage = ExtractRulingFactsStage()
        retrieve_stage = RetrieveStage(
            retrieval_service=retrieval_svc,
            evidence_repository=evidence_repo,
        )
        generate_memo_sections_stage = GenerateMemoSectionsStage(
            memo_section_service=memo_section_service,
            lineage_link_repository=lineage_link_repo,
        )
        citations_stage = CitationBuilderStage(
            citation_builder=CitationBuilder(citation_repository=citation_repo)
        )

        knowledge_engine = _make_knowledge_engine(db_session)
        knowledge_retrieve_stage = KnowledgeRetrieveStage(
            engine=knowledge_engine,
            workflow_type="tariff_classification",
        )
        knowledge_store_stage = KnowledgeStoreStage(
            engine=knowledge_engine,
            workflow_type="tariff_classification",
        )

        quality_gate_stage = _make_quality_gate_stage(db_session, memo_section_repo)
        focused_update_stage = _make_focused_update_stage(db_session)

        # Phase 4: Multi-document stages
        from backend.repositories.document import DocumentRepository
        from backend.storage.local import LocalStorageBackend

        document_repo = DocumentRepository(db_session)
        storage = LocalStorageBackend(settings.storage_path)

        discover_documents_stage = DiscoverDocumentsStage(document_repository=document_repo)
        load_product_content_stage = LoadProductContentStage(
            document_repository=document_repo,
            storage=storage,
        )
        load_ruling_content_stage = LoadRulingContentStage(
            document_repository=document_repo,
            storage=storage,
        )
        reconcile_documents_stage = ReconcileDocumentsStage()

        superdocs_upload_stage = None
        superdocs_instruction_stage = None
        superdocs_approval_stage = None
        superdocs_export_stage = None
        has_superdocs = hasattr(settings, "superdocs_api_key") and settings.superdocs_api_key

        if has_superdocs:
            from backend.integrations.superdocs import (
                SuperDocsClient,
                SessionManager,
                DocumentBridge,
                InstructionBuilder,
            )
            from backend.services.export import ExportService as CanonicalExportService
            from backend.repositories.superdocs_session import SuperDocsSessionRepository
            from backend.repositories.document import DocumentRepository
            from backend.repositories.export import ExportRepository
            from backend.repositories.review import ReviewRepository, ClaimRepository
            from backend.repositories.workflow import WorkflowRunRepository, WorkflowStageRepository
            from backend.repositories.workspace import WorkspaceRepository
            from backend.storage.local import LocalStorageBackend

            superdocs_client = SuperDocsClient()
            session_repo = SuperDocsSessionRepository(db_session)
            session_manager = SessionManager(superdocs_client, session_repo)
            document_repo = DocumentRepository(db_session)
            storage = LocalStorageBackend(settings.storage_path)
            document_bridge = DocumentBridge(superdocs_client, session_manager, document_repo)
            instruction_builder = InstructionBuilder()
            export_repo = ExportRepository(db_session)

            canonical_export_service = CanonicalExportService(
                export_repository=export_repo,
                review_repository=ReviewRepository(db_session),
                claim_repository=ClaimRepository(db_session),
                workspace_repository=WorkspaceRepository(db_session),
                document_repository=document_repo,
                run_repository=WorkflowRunRepository(db_session),
                stage_repository=WorkflowStageRepository(db_session),
                storage=storage,
                memo_section_repository=memo_section_repo,
            )

            superdocs_upload_stage = SuperDocsUploadStage(
                superdocs_client=superdocs_client,
                session_manager=session_manager,
                document_bridge=document_bridge,
                document_repository=document_repo,
                storage=storage,
            )
            superdocs_instruction_stage = SuperDocsInstructionStage(
                superdocs_client=superdocs_client,
                instruction_builder=instruction_builder,
                memo_section_repository=memo_section_repo,
                document_repository=document_repo,
            )
            superdocs_approval_stage = _make_superdocs_approval_stage(db_session)
            superdocs_export_stage = SuperDocsExportStage(
                export_service=canonical_export_service,
                document_repository=document_repo,
                storage_backend=storage,
            )

        if has_superdocs:
            stages = [
                superdocs_upload_stage,
                focused_update_stage,
                discover_documents_stage,
                load_product_content_stage,
                load_ruling_content_stage,
                knowledge_retrieve_stage,
                extract_product_facts_stage,
                extract_ruling_facts_stage,
                reconcile_documents_stage,
                retrieve_stage,
                generate_memo_sections_stage,
                citations_stage,
                quality_gate_stage,
                superdocs_instruction_stage,
                superdocs_approval_stage,
                superdocs_export_stage,
                knowledge_store_stage,
            ]
        else:
            stages = [
                focused_update_stage,
                discover_documents_stage,
                load_product_content_stage,
                load_ruling_content_stage,
                knowledge_retrieve_stage,
                extract_product_facts_stage,
                extract_ruling_facts_stage,
                reconcile_documents_stage,
                retrieve_stage,
                generate_memo_sections_stage,
                citations_stage,
                quality_gate_stage,
                knowledge_store_stage,
            ]

        return stages

    return [extract_stage, generate_stage]


def _registry_stage_names(has_superdocs: bool) -> list[str]:
    """Stage names for registry metadata; must match edges."""
    if has_superdocs:
        return [
            "superdocs_upload",
            "focused_update",
            "discover_documents",
            "load_product_content",
            "load_ruling_content",
            "knowledge_retrieve",
            "extract_product_facts",
            "extract_ruling_facts",
            "reconcile_documents",
            "retrieve",
            "generate_memo_sections",
            "citations",
            "quality_gate",
            "superdocs_instruction",
            "superdocs_approval",
            "superdocs_export",
            "knowledge_store",
        ]
    return [
        "focused_update",
        "discover_documents",
        "load_product_content",
        "load_ruling_content",
        "knowledge_retrieve",
        "extract_product_facts",
        "extract_ruling_facts",
        "reconcile_documents",
        "retrieve",
        "generate_memo_sections",
        "citations",
        "quality_gate",
        "knowledge_store",
    ]


def _make_registry_stub_stage(name: str) -> StageNode:
    """Non-executable placeholder so registry validation passes at startup without a DB."""

    class RegistryStubStage(StageNode):
        def __init__(self, stage_name: str):
            super().__init__(stage_name)

        async def execute(self, state):
            raise RuntimeError(
                f"Stage '{self.name}' is a registry placeholder; "
                "use build_tariff_stages(db_session) at runtime"
            )

    return RegistryStubStage(name)


def build_registry_stages(has_superdocs: bool) -> list[StageNode]:
    """Build registry-safe stub stages matching the configured edge graph."""
    return [_make_registry_stub_stage(name) for name in _registry_stage_names(has_superdocs)]


def _make_claim_repo(session):
    """Create ClaimRepository with full query methods."""
    from backend.repositories.review import ClaimRepository

    return ClaimRepository(session)


def _make_knowledge_engine(session):
    """Create KnowledgeEngine with its repository."""
    from backend.core.knowledge.engine import KnowledgeEngine
    from backend.repositories.knowledge import KnowledgeRepository
    repo = KnowledgeRepository(session)
    return KnowledgeEngine(repository=repo)


def _make_quality_gate_stage(session, memo_section_repo=None):
    """Create QualityGateStage with repositories, baseline contradiction check, and memo grounding check."""
    from backend.core.quality_gate.stage import QualityGateStage
    from backend.core.quality_gate.baseline_check import BaselineContradictionCheck
    from backend.core.quality_gate.memo_grounding_check import MemoGroundingCheck
    from backend.repositories.quality_gate import QualityGateConfigRepository, QualityGateResultRepository
    from backend.repositories.document import DocumentChunkRepository
    from backend.repositories.lineage import LineageLinkRepository

    config_repo = QualityGateConfigRepository(session)
    result_repo = QualityGateResultRepository(session)
    chunk_repo = DocumentChunkRepository(session)
    claim_repo = _make_claim_repo(session)
    lineage_repo = LineageLinkRepository(session)

    baseline_check = BaselineContradictionCheck(
        claim_repo=claim_repo,
        chunk_repo=chunk_repo,
        lineage_repo=lineage_repo,
        memo_section_repo=memo_section_repo,
    )

    memo_grounding_check = MemoGroundingCheck(
        memo_section_repo=memo_section_repo,
    )

    return QualityGateStage(
        checks=[baseline_check, memo_grounding_check],
        config_repository=config_repo,
        result_repository=result_repo,
    )


def _make_superdocs_approval_stage(session):
    """Create SuperDocsApprovalStage with all dependencies."""
    from backend.integrations.superdocs import (
        SuperDocsClient,
        SessionManager,
        ApprovalHandler,
    )
    from backend.repositories.superdocs_session import SuperDocsSessionRepository
    from backend.repositories.lineage import LineageLinkRepository
    from backend.repositories.review import ReviewRepository
    from backend.services.review import ReviewService

    superdocs_client = SuperDocsClient()
    session_repo = SuperDocsSessionRepository(session)
    session_manager = SessionManager(superdocs_client, session_repo)

    claim_repo = _make_claim_repo(session)
    lineage_repo = LineageLinkRepository(session)
    review_repo = ReviewRepository(session)

    approval_handler = ApprovalHandler(
        superdocs_client=superdocs_client,
        session_manager=session_manager,
        claim_repository=claim_repo,
        review_repository=review_repo,
        lineage_repository=lineage_repo,
    )

    return SuperDocsApprovalStage(
        superdocs_client=superdocs_client,
        session_manager=session_manager,
        approval_handler=approval_handler,
    )


def _make_focused_update_stage(session):
    """Create FocusedUpdateStage with all dependencies."""
    from backend.modules.tariff.stages.focused_update import FocusedUpdateStage
    from backend.services.impact_analysis import ImpactAnalysisService
    from backend.repositories.workflow import WorkflowRunRepository
    from backend.repositories.document import DocumentRepository, DocumentChunkRepository
    from backend.repositories.lineage import LineageLinkRepository

    run_repo = WorkflowRunRepository(session)
    claim_repo = _make_claim_repo(session)
    doc_repo = DocumentRepository(session)
    chunk_repo = DocumentChunkRepository(session)
    lineage_repo = LineageLinkRepository(session)

    impact_service = ImpactAnalysisService(
        workflow_run_repo=run_repo,
        claim_repo=claim_repo,
        document_repo=doc_repo,
        chunk_repo=chunk_repo,
    )

    return FocusedUpdateStage(
        impact_service=impact_service,
        claim_repository=claim_repo,
        lineage_repository=lineage_repo,
    )


def register_tariff_workflow():
    """Register the tariff classification workflow in the registry."""
    has_superdocs = hasattr(settings, "superdocs_api_key") and settings.superdocs_api_key
    stages = build_registry_stages(has_superdocs)

    if has_superdocs:
        edges = [
            ("superdocs_upload", "focused_update"),
            ("focused_update", "discover_documents"),
            ("discover_documents", "load_product_content"),
            ("load_product_content", "load_ruling_content"),
            ("load_ruling_content", "knowledge_retrieve"),
            ("knowledge_retrieve", "extract_product_facts"),
            ("extract_product_facts", "extract_ruling_facts"),
            ("extract_ruling_facts", "reconcile_documents"),
            ("reconcile_documents", "retrieve"),
            ("retrieve", "generate_memo_sections"),
            ("generate_memo_sections", "citations"),
            ("citations", "quality_gate"),
            ("quality_gate", "superdocs_instruction"),
            ("superdocs_instruction", "superdocs_approval"),
            ("superdocs_approval", "superdocs_export"),
            ("superdocs_export", "knowledge_store"),
            ("knowledge_store", "END"),
        ]
        description = (
            "Structured tariff classification memo with multi-document support: "
            "discover documents, extract facts, reconcile, generate sections, "
            "quality gate, SuperDocs instruction/approval/export"
        )
    else:
        edges = [
            ("focused_update", "discover_documents"),
            ("discover_documents", "load_product_content"),
            ("load_product_content", "load_ruling_content"),
            ("load_ruling_content", "knowledge_retrieve"),
            ("knowledge_retrieve", "extract_product_facts"),
            ("extract_product_facts", "extract_ruling_facts"),
            ("extract_ruling_facts", "reconcile_documents"),
            ("reconcile_documents", "retrieve"),
            ("retrieve", "generate_memo_sections"),
            ("generate_memo_sections", "citations"),
            ("citations", "quality_gate"),
            ("quality_gate", "knowledge_store"),
            ("knowledge_store", "END"),
        ]
        description = (
            "Structured tariff classification memo with multi-document support: "
            "discover documents, extract facts, reconcile, generate sections, quality gate"
        )

    from backend.modules.tariff.llm_config import DEFAULT_TARIFF_LLM_MODEL

    workflow_registry.register(
        workflow_name="tariff_classification",
        stages=stages,
        edges=edges,
        state_schema=TariffWorkflowState,
        description=description,
        configuration_schema={
            "type": "object",
            "properties": {
                "llm_model": {"type": "string", "default": DEFAULT_TARIFF_LLM_MODEL},
                "use_superdocs": {"type": "boolean", "default": has_superdocs},
            },
        },
    )

    logger.info("tariff_workflow_registered")
