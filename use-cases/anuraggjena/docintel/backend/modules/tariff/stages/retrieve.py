from typing import Any, Dict, List

from backend.core.workflow.stage import StageNode
from backend.modules.tariff.schemas import TariffWorkflowState
from backend.services.retrieval import RetrievalService
from backend.repositories.evidence import EvidenceRepository
from backend.logging_config import get_logger

logger = get_logger(__name__)

TOP_K = 8


class RetrieveStage(StageNode[TariffWorkflowState]):
    """
    Ingest document chunks, embed them, and retrieve the most relevant
    chunks for tariff classification. Creates Evidence records.
    """

    def __init__(
        self,
        retrieval_service: RetrievalService,
        evidence_repository: EvidenceRepository,
    ):
        super().__init__("retrieve")
        self._retrieval_svc = retrieval_service
        self._evidence_repo = evidence_repository

    async def execute(self, state: TariffWorkflowState) -> Dict[str, Any]:
        workflow_run_id = state.workflow_run_id

        # Build list of documents to index
        documents_to_index = []

        # Add product spec content
        if state.product_spec_content:
            product_spec_ids = state.product_spec_document_ids
            if product_spec_ids:
                documents_to_index.append({
                    "id": product_spec_ids[0],
                    "content": state.product_spec_content,
                })

        # Add ruling content
        for ruling_id, content in state.ruling_content_map.items():
            if content:
                documents_to_index.append({
                    "id": ruling_id,
                    "content": content,
                })

        # Fallback to primary document if no categorized documents
        if not documents_to_index and state.document_content:
            documents_to_index.append({
                "id": state.document_id,
                "content": state.document_content,
            })

        if not documents_to_index:
            logger.warning("retrieve_stage_skipped", reason="no_document_content")
            return {
                "retrieve_completed": True,
                "retrieved_chunks": [],
                "evidence_ids": [],
            }

        logger.info("ingesting_documents", count=len(documents_to_index))

        # Ingest all documents (chunk + embed + store)
        indexed_doc_ids = []
        for doc in documents_to_index:
            await self._retrieval_svc.ingest_document(
                text=doc["content"],
                document_id=str(doc["id"]),
            )
            indexed_doc_ids.append(str(doc["id"]))

        # Build query from product facts if available
        if state.product_facts:
            query_parts = []
            if state.product_facts.product_name:
                query_parts.append(state.product_facts.product_name)
            if state.product_facts.material_composition:
                query_parts.append(state.product_facts.material_composition)
            if state.product_facts.intended_use:
                query_parts.append(state.product_facts.intended_use)
            query = " ".join(query_parts[:3])  # Limit query length
        else:
            # Fallback: use first document content
            query = documents_to_index[0]["content"][:500]

        logger.info("semantic_search", query_length=len(query), document_count=len(indexed_doc_ids))

        # Semantic search across all indexed documents
        results = await self._retrieval_svc.search(
            query=query,
            document_ids=indexed_doc_ids,
            top_k=TOP_K,
        )

        # Persist Evidence records
        evidence_ids: List[str] = []
        retrieved_chunks: List[Dict[str, Any]] = []

        for result in results:
            try:
                evidence = await self._evidence_repo.create(
                    workflow_run_id=str(workflow_run_id),
                    document_id=str(result.document_id),
                    chunk_id=result.chunk_id,
                    extracted_text=result.text,
                    evidence_type="retrieved_chunk",
                    page_number=str(result.page_number) if result.page_number else None,
                    relevance_score=result.score,
                )
                evidence_ids.append(str(evidence.id))
            except Exception as exc:
                logger.error("evidence_create_failed", error=str(exc))

            retrieved_chunks.append({
                "chunk_id": result.chunk_id,
                "document_id": result.document_id,
                "text": result.text,
                "score": result.score,
            })

        logger.info(
            "retrieve_stage_complete",
            chunks_retrieved=len(results),
            evidence_created=len(evidence_ids),
        )

        return {
            "retrieve_completed": True,
            "retrieved_chunks": retrieved_chunks,
            "evidence_ids": evidence_ids,
        }
