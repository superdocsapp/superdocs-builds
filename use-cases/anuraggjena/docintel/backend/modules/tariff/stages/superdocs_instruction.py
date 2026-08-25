"""Submit structured memo sections to SuperDocs for in-document editing."""

from typing import Dict, Any
from uuid import UUID

from backend.core.workflow.stage import StageNode
from backend.modules.tariff.schemas import TariffWorkflowState
from backend.integrations.superdocs.client import SuperDocsClient
from backend.integrations.superdocs.instruction_builder import InstructionBuilder
from backend.repositories.memo_section import MemoSectionRepository
from backend.repositories.document import DocumentRepository
from backend.logging_config import get_logger

logger = get_logger(__name__)


class SuperDocsInstructionStage(StageNode[TariffWorkflowState]):
    """Build structured memo instruction and submit to SuperDocs."""

    def __init__(
        self,
        superdocs_client: SuperDocsClient,
        instruction_builder: InstructionBuilder,
        memo_section_repository: MemoSectionRepository,
        document_repository: DocumentRepository,
    ):
        super().__init__("superdocs_instruction")
        self._client = superdocs_client
        self._builder = instruction_builder
        self._section_repo = memo_section_repository
        self._document_repo = document_repository

    async def execute(self, state: TariffWorkflowState) -> Dict[str, Any]:
        if not state.superdocs_session_id:
            logger.warning("superdocs_instruction_skipped", reason="no_session")
            return {"superdocs_job_id": None}

        sections = await self._section_repo.list_by_run(UUID(state.workflow_run_id))
        active_sections = [s for s in sections if s.status != "skipped"]

        # Build a cache of document_id → filename for enriching source labels.
        doc_name_cache: dict = {}

        async def _resolve_doc_name(doc_id: str) -> str | None:
            if doc_id in doc_name_cache:
                return doc_name_cache[doc_id]
            try:
                doc = await self._document_repo.get_by_id(UUID(doc_id))
                name = doc.filename if doc else None
            except Exception:
                name = None
            doc_name_cache[doc_id] = name
            return name

        async def _enrich_attribution(attrs: list) -> list:
            enriched = []
            for attr in attrs:
                attr = dict(attr)
                doc_id = attr.get("document_id")
                if doc_id and not attr.get("document_name"):
                    name = await _resolve_doc_name(doc_id)
                    if name:
                        attr["document_name"] = name
                enriched.append(attr)
            return enriched

        section_payloads = []
        for s in active_sections:
            enriched_attrs = await _enrich_attribution(s.source_attribution or [])
            section_payloads.append({
                "title": s.title,
                "section_order": s.section_order,
                "section_type": s.section_type,
                "content": s.content,
                "analyst_reasoning": s.analyst_reasoning,
                "source_attribution": enriched_attrs,
                "structured_data": s.structured_data,
            })

        image_refs = []
        if state.image_document_ids:
            for doc_id in state.image_document_ids:
                doc = await self._document_repo.get_by_id(UUID(doc_id))
                if doc:
                    image_refs.append({"filename": doc.filename, "document_id": str(doc.id)})

        instruction = self._builder.build_structured_memo_instruction(
            sections=section_payloads,
            image_refs=image_refs,
        )

        job = await self._client.chat_async(
            session_id=state.superdocs_session_id,
            message=instruction,
            approval_mode="ask_every_time",
            response_mode="compact",
        )

        logger.info("superdocs_instruction_submitted", job_id=job.job_id)
        return {"superdocs_job_id": job.job_id}
