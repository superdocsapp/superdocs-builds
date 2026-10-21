import asyncio
import json
from typing import Dict, Any, List, Optional, Set, Tuple
from uuid import UUID

from backend.core.workflow.stage import StageNode
from backend.modules.tariff.schemas import TariffWorkflowState
from backend.modules.tariff.memo_types import (
    GENERATION_ORDER,
    SECTION_ORDER,
    SECTION_TITLES,
    MemoSectionType,
    MemoSectionOutput,
    ProductFacts,
)
from backend.modules.tariff.prompts_memo import (
    SECTION_GENERATION_PROMPT,
    SECTION_GENERATION_PROMPT_NO_RULINGS,
)
from backend.modules.tariff.llm_config import get_tariff_llm_model, get_tariff_llm_provider
from backend.core.llm.provider import LLMMessage
from backend.modules.tariff.memo_grounding import sanitize_memo_text
from backend.services.memo_section import MemoSectionService
from backend.logging_config import get_logger

logger = get_logger(__name__)

# Groq openai/gpt-oss-20b on-demand tier: 8000 tokens per minute (input + output combined)
GROQ_TPM_LIMIT = 8000
# Schema instruction (~600 tokens) + system message + tokenization variance (200)
TOKEN_SAFETY_MARGIN = 800
CHARS_PER_TOKEN = 4         # conservative estimate: 1 token ≈ 4 characters
MAX_EVIDENCE_CHARS = 800    # max chars per evidence chunk in prompt
MAX_EVIDENCE_CHUNKS = 4     # max chunks to include per section

# Sections that need ruling facts for grounding
_RULING_REQUIRED_SECTIONS = {
    MemoSectionType.RELEVANT_PREVIOUS_RULINGS,
    MemoSectionType.CLASSIFICATION_ANALYSIS,
    MemoSectionType.ALTERNATIVES_CONSIDERED,
    MemoSectionType.ALTERNATIVES_REJECTED,
    MemoSectionType.RECOMMENDED_CLASSIFICATION,
    MemoSectionType.SUPPORTING_CITATIONS,
    MemoSectionType.EXECUTIVE_SUMMARY,
}


class GenerateMemoSectionsStage(StageNode[TariffWorkflowState]):
    """Generate structured memo sections with per-section LLM calls."""

    def __init__(
        self,
        memo_section_service: Optional[MemoSectionService] = None,
        lineage_link_repository=None,
    ):
        super().__init__("generate_memo_sections")
        self.llm = get_tariff_llm_provider()
        self._memo_service = memo_section_service
        self._lineage_link_repo = lineage_link_repository

    def _should_skip_section(self, section_type: MemoSectionType, state: TariffWorkflowState) -> bool:
        if section_type == MemoSectionType.PRODUCT_IMAGES and not state.image_document_ids:
            return True
        if section_type == MemoSectionType.RELEVANT_PREVIOUS_RULINGS and not state.ruling_facts:
            return True
        if section_type == MemoSectionType.REVIEWER_NOTES:
            return True
        return False

    def _should_generate_section(self, section_type: MemoSectionType, state: TariffWorkflowState) -> bool:
        if state.sections_to_regenerate:
            if section_type == MemoSectionType.EXECUTIVE_SUMMARY:
                return True
            return section_type.value in state.sections_to_regenerate
        return True

    def _section_order(self, section_type: MemoSectionType) -> int:
        for entry in SECTION_ORDER:
            if entry.section_type == section_type:
                return entry.section_order
        raise ValueError(f"Unknown section type: {section_type}")

    def _safe_max_tokens(self, prompt: str) -> int:
        """Compute safe max_tokens so input + output fits within TPM limit."""
        estimated_input = len(prompt) // CHARS_PER_TOKEN
        available = GROQ_TPM_LIMIT - estimated_input - TOKEN_SAFETY_MARGIN
        return max(512, available)

    def _format_evidence(self, section_type: MemoSectionType, state: TariffWorkflowState) -> str:
        """Return only evidence relevant to this section, capped to budget."""
        if not state.retrieved_chunks:
            return "No evidence retrieved."

        section_val = section_type.value
        relevant = []
        generic = []

        for chunk in state.retrieved_chunks:
            text = chunk.get("text", chunk.get("content", ""))
            relevance = chunk.get("section_relevance", [])
            if section_val in relevance:
                relevant.append(text)
            elif not relevance:
                generic.append(text)

        # Use section-relevant chunks first, fall back to generic
        chosen = (relevant + generic)[:MAX_EVIDENCE_CHUNKS]
        parts = [f"- {c[:MAX_EVIDENCE_CHARS]}" for c in chosen if c]
        return "\n".join(parts) if parts else "No evidence retrieved."

    def _build_prompt(
        self,
        section_type: MemoSectionType,
        state: TariffWorkflowState,
        baseline_content: str = "",
    ) -> str:
        product_facts = state.product_facts or ProductFacts()
        evidence = self._format_evidence(section_type, state)

        from backend.modules.tariff.prompts_memo import _section_focus
        focus = _section_focus(section_type.value)

        needs_rulings = section_type in _RULING_REQUIRED_SECTIONS
        if needs_rulings and state.ruling_facts:
            ruling_json = json.dumps(
                [r.model_dump(exclude={"source_locations"}) for r in state.ruling_facts],
                indent=2,
            )
            prompt = SECTION_GENERATION_PROMPT.format(
                section_title=SECTION_TITLES[section_type],
                section_type=section_type.value,
                section_focus=focus,
                product_facts=product_facts.model_dump_json(indent=2),
                ruling_facts=ruling_json,
                evidence=evidence,
                prior_knowledge=state.prior_knowledge or "None",
                baseline_section=baseline_content or "None",
            )
        else:
            prompt = SECTION_GENERATION_PROMPT_NO_RULINGS.format(
                section_title=SECTION_TITLES[section_type],
                section_type=section_type.value,
                section_focus=focus,
                product_facts=product_facts.model_dump_json(indent=2),
                evidence=evidence,
                prior_knowledge=state.prior_knowledge or "None",
                baseline_section=baseline_content or "None",
            )

        # Trim prompt if it would leave fewer than 512 tokens for output
        max_input_chars = (GROQ_TPM_LIMIT - 512 - TOKEN_SAFETY_MARGIN) * CHARS_PER_TOKEN
        if len(prompt) > max_input_chars:
            prompt = prompt[:max_input_chars]

        return prompt

    async def _create_lineage_for_knowledge(
        self,
        state: TariffWorkflowState,
        claim_id: str,
        adopted_ids: List[str],
    ) -> None:
        if not self._lineage_link_repo or not adopted_ids:
            return
        for entry_id in adopted_ids:
            try:
                await self._lineage_link_repo.create_link(
                    source_type="claim",
                    source_id=UUID(claim_id),
                    target_type="knowledge_entry",
                    target_id=UUID(entry_id),
                    link_type="derived_from_knowledge",
                    workflow_run_id=UUID(state.workflow_run_id),
                    stage_name="generate_memo_sections",
                    metadata={"relevance": "adopted_in_section"},
                )
            except Exception as exc:
                logger.error("knowledge_lineage_failed", error=str(exc))

    async def _generate_section(
        self,
        section_type: MemoSectionType,
        state: TariffWorkflowState,
        summary_context: str = "",
    ) -> Tuple[MemoSectionType, Optional[Any], Optional[Any]]:
        """Generate one section. Returns (section_type, output, existing_section)."""
        existing_section = None
        if self._memo_service and state.workflow_run_id:
            existing_section = await self._memo_service._section_repo.get_by_run_and_type(
                workflow_run_id=UUID(state.workflow_run_id),
                section_type=section_type.value
            )

        # Skip
        if self._should_skip_section(section_type, state):
            return (section_type, None, existing_section)

        # Reuse
        if not self._should_generate_section(section_type, state):
            return (section_type, None, existing_section)

        if existing_section and not (
            state.sections_to_regenerate and section_type.value in state.sections_to_regenerate
        ):
            return (section_type, None, existing_section)

        prompt = self._build_prompt(section_type, state)
        if summary_context:
            prompt += summary_context

        messages = [
            LLMMessage(role="system", content="You draft evidence-grounded tariff memo sections."),
            LLMMessage(role="user", content=prompt),
        ]
        max_tokens = self._safe_max_tokens(prompt)

        logger.info(
            "generating_memo_section",
            section=section_type.value,
            prompt_chars=len(prompt),
            max_tokens=max_tokens,
        )

        output = await self.llm.generate_structured(
            messages=messages,
            model=get_tariff_llm_model(),
            response_schema=MemoSectionOutput,
            temperature=0.4,
            max_tokens=max_tokens,
        )
        return (section_type, output, existing_section)

    async def execute(self, state: TariffWorkflowState) -> Dict[str, Any]:
        if not state.product_facts and not state.document_content:
            raise ValueError("No product facts or document content for memo generation")

        memo_section_ids: List[str] = []
        claim_ids: List[str] = []
        adopted_all: Set[str] = set()
        generated_sections: Dict[str, str] = {}

        # Split: all sections except executive summary can run in parallel
        body_sections = [s for s in GENERATION_ORDER if s != MemoSectionType.EXECUTIVE_SUMMARY]

        # --- Phase 1: generate all body sections concurrently ---
        # Concurrency allows fast parallel generation across Gemini models.
        sem = asyncio.Semaphore(12)

        async def _guarded(s):
            async with sem:
                return await self._generate_section(s, state)

        results = await asyncio.gather(
            *[_guarded(s) for s in body_sections],
            return_exceptions=False,
        )

        # Persist results in order
        for section_type, output, existing_section in results:
            ids = await self._persist_section(
                section_type, output, existing_section, state, generated_sections
            )
            memo_section_ids.extend(ids[0])
            claim_ids.extend(ids[1])
            adopted_all.update(ids[2])

        # --- Phase 2: executive summary (needs body content) ---
        summary_ctx = ""
        if generated_sections:
            summary_ctx = "\n\n## Completed sections to summarize:\n"
            for stype, preview in generated_sections.items():
                summary_ctx += f"\n### {stype}\n{preview[:300]}\n"
            max_prompt_chars = (GROQ_TPM_LIMIT - 512 - TOKEN_SAFETY_MARGIN) * CHARS_PER_TOKEN

        section_type = MemoSectionType.EXECUTIVE_SUMMARY
        _, output, existing_section = await self._generate_section(
            section_type, state, summary_context=summary_ctx if generated_sections else ""
        )
        ids = await self._persist_section(
            section_type, output, existing_section, state, generated_sections
        )
        memo_section_ids.extend(ids[0])
        claim_ids.extend(ids[1])
        adopted_all.update(ids[2])

        logger.info("memo_sections_generated", count=len(memo_section_ids))
        return {
            "memo_section_ids": memo_section_ids,
            "claim_ids": claim_ids,
            "generate_memo_completed": True,
            "adopted_knowledge_entry_ids": list(adopted_all),
        }

    async def _persist_section(
        self,
        section_type: MemoSectionType,
        output: Optional[Any],
        existing_section: Optional[Any],
        state: TariffWorkflowState,
        generated_sections: Dict[str, str],
    ) -> Tuple[List[str], List[str], Set[str]]:
        """Persist one section result. Returns (section_ids, claim_ids, adopted_knowledge_ids)."""
        sec_ids: List[str] = []
        cl_ids: List[str] = []
        adopted: Set[str] = set()

        # Skip case
        if self._should_skip_section(section_type, state):
            if self._memo_service and state.workflow_run_id:
                if existing_section and existing_section.status == "skipped":
                    sec_ids.append(str(existing_section.id))
                    claims = await self._memo_service._claim_repo.list_by_run(UUID(state.workflow_run_id))
                    section_claim = next(
                        (c for c in claims if c.source_stage == "generate_memo_sections"
                         and str(existing_section.id) in c.content), None
                    )
                    if section_claim:
                        cl_ids.append(str(section_claim.id))
                else:
                    section, claim = await self._memo_service.create_section_with_claim(
                        workflow_run_id=UUID(state.workflow_run_id),
                        section_type=section_type.value,
                        title=SECTION_TITLES[section_type],
                        section_order=self._section_order(section_type),
                        content="",
                        status="skipped",
                    )
                    sec_ids.append(str(section.id))
                    cl_ids.append(str(claim.id))
            return sec_ids, cl_ids, adopted

        # Reuse existing without LLM call
        if output is None and existing_section:
            sec_ids.append(str(existing_section.id))
            if self._memo_service and state.workflow_run_id:
                claims = await self._memo_service._claim_repo.list_by_run(UUID(state.workflow_run_id))
                section_claim = next(
                    (c for c in claims if c.source_stage == "generate_memo_sections"
                     and str(existing_section.id) in c.content), None
                )
                if section_claim:
                    cl_ids.append(str(section_claim.id))
            generated_sections[section_type.value] = existing_section.content or ""
            return sec_ids, cl_ids, adopted

        if output is None:
            return sec_ids, cl_ids, adopted

        # Sanitize text to remove meta AI language and orphan headings
        clean_content, clean_reasoning = sanitize_memo_text(
            output.content, output.analyst_reasoning
        )
        output.content = clean_content
        output.analyst_reasoning = clean_reasoning

        # Newly generated
        structured_data = None
        if output.alternatives:
            structured_data = {"alternatives": [a.model_dump() for a in output.alternatives]}
        if output.recommendation:
            structured_data = structured_data or {}
            structured_data["recommendation"] = output.recommendation.model_dump()

        if self._memo_service and state.workflow_run_id:
            if existing_section:
                await self._memo_service._section_repo.update(
                    existing_section.id,
                    content=output.content,
                    analyst_reasoning=output.analyst_reasoning,
                    source_attribution=output.source_attribution,
                    evidence_refs=state.evidence_ids[:5],
                    confidence=output.confidence,
                    structured_data=structured_data,
                    status="pending",
                )
                sec_ids.append(str(existing_section.id))
                claims = await self._memo_service._claim_repo.list_by_run(UUID(state.workflow_run_id))
                section_claim = next(
                    (c for c in claims if c.source_stage == "generate_memo_sections"
                     and str(existing_section.id) in c.content), None
                )
                if section_claim:
                    cl_ids.append(str(section_claim.id))
                    await self._create_lineage_for_knowledge(
                        state, str(section_claim.id), output.adopted_knowledge_entry_ids
                    )
            else:
                section, claim = await self._memo_service.create_section_with_claim(
                    workflow_run_id=UUID(state.workflow_run_id),
                    section_type=section_type.value,
                    title=SECTION_TITLES[section_type],
                    section_order=self._section_order(section_type),
                    content=output.content,
                    analyst_reasoning=output.analyst_reasoning,
                    source_attribution=output.source_attribution,
                    evidence_refs=state.evidence_ids[:5],
                    confidence=output.confidence,
                    structured_data=structured_data,
                )
                sec_ids.append(str(section.id))
                cl_ids.append(str(claim.id))
                await self._create_lineage_for_knowledge(
                    state, str(claim.id), output.adopted_knowledge_entry_ids
                )
            adopted.update(output.adopted_knowledge_entry_ids)

        generated_sections[section_type.value] = output.content
        return sec_ids, cl_ids, adopted

