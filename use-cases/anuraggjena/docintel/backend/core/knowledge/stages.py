from typing import Any, Dict, List, Optional
from uuid import UUID

from backend.core.workflow.stage import StageNode
from backend.core.knowledge.engine import KnowledgeEngine
from backend.logging_config import get_logger

logger = get_logger(__name__)


class KnowledgeRetrieveStage(StageNode):
    """Pre-stage: loads relevant prior knowledge into workflow state."""

    def __init__(self, engine: KnowledgeEngine, workflow_type: str, tags_key: str = "tags"):
        super().__init__(name="knowledge_retrieve")
        self.engine = engine
        self.workflow_type = workflow_type
        self.tags_key = tags_key

    async def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        # Support both dict and Pydantic model state
        workspace_id = state.get("workspace_id") if isinstance(state, dict) else getattr(state, "workspace_id", None)
        if not workspace_id:
            logger.warning("knowledge_retrieve_skipped", reason="no workspace_id")
            return {"prior_knowledge": "", "prior_knowledge_entries": []}

        tags = state.get(self.tags_key, []) if isinstance(state, dict) else getattr(state, self.tags_key, [])

        try:
            context = await self.engine.retrieve_as_context(
                workspace_id=UUID(workspace_id),
                workflow_type=self.workflow_type,
                tags=tags if tags else None,
                limit=5
            )
            entries = await self.engine.retrieve(
                workspace_id=UUID(workspace_id),
                workflow_type=self.workflow_type,
                tags=tags if tags else None,
                limit=5
            )
            logger.info("knowledge_retrieved", count=len(entries), workflow_type=self.workflow_type)
            return {
                "prior_knowledge": context,
                "prior_knowledge_entries": [str(e.id) for e in entries]
            }
        except Exception as e:
            logger.error("knowledge_retrieve_failed", error=str(e))
            return {"prior_knowledge": "", "prior_knowledge_entries": []}


class KnowledgeStoreStage(StageNode):
    """Post-stage: persists workflow outputs as knowledge entries."""

    def __init__(
        self,
        engine: KnowledgeEngine,
        workflow_type: str,
        claims_key: str = "claims",
        output_key: str = "generated_output"
    ):
        super().__init__(name="knowledge_store")
        self.engine = engine
        self.workflow_type = workflow_type
        self.claims_key = claims_key
        self.output_key = output_key

    async def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        # Support both dict and Pydantic model state
        workspace_id = state.get("workspace_id") if isinstance(state, dict) else getattr(state, "workspace_id", None)
        if not workspace_id:
            logger.warning("knowledge_store_skipped", reason="no workspace_id")
            return {"knowledge_stored": 0}

        run_id = state.get("workflow_run_id") if isinstance(state, dict) else getattr(state, "workflow_run_id", None)
        document_id = state.get("document_id") if isinstance(state, dict) else getattr(state, "document_id", None)
        stored = 0

        # 1. Store claims / tariff claims
        claims = state.get(self.claims_key) if isinstance(state, dict) else getattr(state, self.claims_key, None)
        if not claims:
            claims = state.get("extracted_claims") if isinstance(state, dict) else getattr(state, "extracted_claims", [])

        for claim in (claims or []):
            if hasattr(claim, "hs_code"):
                content = f"HS Code: {claim.hs_code} - {claim.description}. Applicable Duty Rate: {claim.duty_rate}"
                if getattr(claim, "notes", None):
                    content += f". Notes: {claim.notes}"
                tags = ["hs_code", "tariff_classification", "claim", str(claim.hs_code)]
                confidence_score = 1.0
            elif isinstance(claim, dict):
                if "hs_code" in claim:
                    content = f"HS Code: {claim['hs_code']} - {claim.get('description', '')}. Applicable Duty Rate: {claim.get('duty_rate', '')}"
                    if claim.get("notes"):
                        content += f". Notes: {claim['notes']}"
                    tags = ["hs_code", "tariff_classification", "claim", str(claim["hs_code"])]
                    confidence_score = 1.0
                else:
                    content = claim.get("content", "")
                    tags = claim.get("tags", ["claim"])
                    confidence_score = claim.get("confidence_score")
            else:
                content = str(claim)
                tags = ["claim"]
                confidence_score = None

            if content:
                try:
                    await self.engine.store(
                        workspace_id=UUID(str(workspace_id)),
                        workflow_type=self.workflow_type,
                        entry_type="claim",
                        content=content,
                        source_run_id=str(run_id) if run_id else None,
                        source_document_id=str(document_id) if document_id else None,
                        confidence_score=float(confidence_score) if confidence_score is not None else None,
                        tags=tags
                    )
                    stored += 1
                except Exception as e:
                    logger.error("knowledge_store_claim_failed", error=str(e))

        # 2. Store product & ruling facts as knowledge claims
        product_facts = state.get("product_facts") if isinstance(state, dict) else getattr(state, "product_facts", None)
        if product_facts:
            name = getattr(product_facts, "product_name", None) or (product_facts.get("product_name") if isinstance(product_facts, dict) else None) or "Product"
            func = getattr(product_facts, "principal_function", None) or (product_facts.get("principal_function") if isinstance(product_facts, dict) else None) or ""
            feats = getattr(product_facts, "key_features", []) or (product_facts.get("key_features", []) if isinstance(product_facts, dict) else [])
            feat_str = ", ".join(feats) if isinstance(feats, list) else str(feats)
            fact_content = f"Product Classification Facts for {name}: Principal Function: {func}. Key Features: {feat_str}."
            try:
                await self.engine.store(
                    workspace_id=UUID(str(workspace_id)),
                    workflow_type=self.workflow_type,
                    entry_type="claim",
                    content=fact_content,
                    source_run_id=str(run_id) if run_id else None,
                    source_document_id=str(document_id) if document_id else None,
                    confidence_score=1.0,
                    tags=["product_facts", "product_spec", "facts"]
                )
                stored += 1
            except Exception as e:
                logger.error("knowledge_store_product_facts_failed", error=str(e))

        ruling_facts = state.get("ruling_facts") if isinstance(state, dict) else getattr(state, "ruling_facts", None)
        if ruling_facts:
            ruling_no = getattr(ruling_facts, "ruling_number", None) or (ruling_facts.get("ruling_number") if isinstance(ruling_facts, dict) else None) or ""
            ruling_hs = getattr(ruling_facts, "hs_code", None) or (ruling_facts.get("hs_code") if isinstance(ruling_facts, dict) else None) or ""
            ruling_analysis = getattr(ruling_facts, "ruling_analysis", None) or (ruling_facts.get("ruling_analysis") if isinstance(ruling_facts, dict) else None) or ""
            ruling_content = f"Precedent Ruling {ruling_no}: HS Code {ruling_hs}. Ruling Analysis: {ruling_analysis}."
            tags = ["ruling_reference", "precedent", "ruling"]
            if ruling_hs:
                tags.append(str(ruling_hs))
            try:
                await self.engine.store(
                    workspace_id=UUID(str(workspace_id)),
                    workflow_type=self.workflow_type,
                    entry_type="claim",
                    content=ruling_content,
                    source_run_id=str(run_id) if run_id else None,
                    source_document_id=str(document_id) if document_id else None,
                    confidence_score=1.0,
                    tags=tags
                )
                stored += 1
            except Exception as e:
                logger.error("knowledge_store_ruling_facts_failed", error=str(e))

        # 3. Store generated sections / reports (Summary + Full Output)
        generated_sections = state.get("generated_sections") if isinstance(state, dict) else getattr(state, "generated_sections", {})
        if not generated_sections and run_id and hasattr(self.engine, "repository") and hasattr(self.engine.repository, "session"):
            try:
                from backend.models.memo_section import MemoSection
                from sqlalchemy import select
                sec_result = await self.engine.repository.session.execute(
                    select(MemoSection)
                    .where(MemoSection.workflow_run_id == UUID(str(run_id)))
                    .order_by(MemoSection.section_order)
                )
                db_sections = list(sec_result.scalars().all())
                if db_sections:
                    generated_sections = {s.section_type: s.content for s in db_sections if s.content and s.status != "skipped"}
            except Exception as e:
                logger.debug("could_not_fetch_db_memo_sections", error=str(e))

        generated_report = state.get(self.output_key) if isinstance(state, dict) else getattr(state, self.output_key, None)
        if not generated_report:
            generated_report = state.get("generated_report") if isinstance(state, dict) else getattr(state, "generated_report", None)

        summary_content = ""
        if isinstance(generated_sections, dict) and generated_sections:
            summary_content = (
                generated_sections.get("executive_summary")
                or generated_sections.get("recommended_classification")
                or generated_sections.get("classification_analysis")
                or ""
            )
        elif generated_report:
            summary_content = generated_report

        if summary_content:
            try:
                await self.engine.store(
                    workspace_id=UUID(str(workspace_id)),
                    workflow_type=self.workflow_type,
                    entry_type="summary",
                    content=summary_content,
                    source_run_id=str(run_id) if run_id else None,
                    source_document_id=str(document_id) if document_id else None,
                    tags=["summary", "recommendation", "tariff_classification"]
                )
                stored += 1
            except Exception as e:
                logger.error("knowledge_store_summary_failed", error=str(e))

        full_output_content = ""
        if isinstance(generated_sections, dict) and len(generated_sections) > 1:
            full_output_content = "\n\n".join(
                f"## {sec_name.replace('_', ' ').title()}\n{sec_text}"
                for sec_name, sec_text in generated_sections.items()
                if sec_text
            )

        if full_output_content:
            try:
                await self.engine.store(
                    workspace_id=UUID(str(workspace_id)),
                    workflow_type=self.workflow_type,
                    entry_type="full_output",
                    content=full_output_content,
                    source_run_id=str(run_id) if run_id else None,
                    source_document_id=str(document_id) if document_id else None,
                    tags=["full_output", "tariff_memo", "complete_memo"]
                )
                stored += 1
            except Exception as e:
                logger.error("knowledge_store_full_output_failed", error=str(e))

        logger.info("knowledge_stored", count=stored, workflow_type=self.workflow_type)
        return {"knowledge_stored": stored}
