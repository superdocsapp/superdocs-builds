import json
from typing import Dict, Any, List, Optional
from uuid import UUID
from backend.core.workflow.stage import StageNode
from backend.modules.tariff.schemas import TariffWorkflowState
from backend.modules.tariff.prompts import GENERATE_PROMPT
from backend.modules.tariff.llm_config import get_tariff_llm_model, get_tariff_llm_provider
from backend.core.llm.provider import LLMMessage
from backend.logging_config import get_logger

logger = get_logger(__name__)


class GenerateStage(StageNode[TariffWorkflowState]):
    """
    Generate tariff classification report from extracted claims.

    If SuperDocs is enabled, also submits the instruction to SuperDocs.
    """

    def __init__(
        self,
        claim_repository=None,
        lineage_link_repository=None,
        superdocs_client=None,
        instruction_builder=None
    ):
        super().__init__("generate")
        self.llm = get_tariff_llm_provider()
        self._claim_repo = claim_repository
        self._lineage_link_repo = lineage_link_repository
        self._superdocs_client = superdocs_client
        self._instruction_builder = instruction_builder

    def _identify_adopted_knowledge(
        self,
        knowledge_entries: List[str],
        generated_report: str
    ) -> List[str]:
        """
        Identify which knowledge entries were actually adopted in the generation.

        For now, uses a simple heuristic: if knowledge entries exist and are non-empty,
        assume all were adopted. Later iterations can add semantic matching.

        Args:
            knowledge_entries: List of knowledge entry IDs from state
            generated_report: The generated report text

        Returns:
            List of knowledge entry IDs that were adopted
        """
        if knowledge_entries and len(knowledge_entries) > 0:
            # Simple heuristic: assume all retrieved knowledge was adopted
            return knowledge_entries
        return []

    async def execute(self, state: TariffWorkflowState) -> Dict[str, Any]:
        """Generate report from claims"""
        logger.info("generating_tariff_report", claims_count=len(state.extracted_claims))

        if not state.extracted_claims:
            raise ValueError("No extracted claims to generate report from")

        # Format claims for prompt
        claims_text = "\n".join([
            f"- HS Code: {claim.hs_code}\n"
            f"  Description: {claim.description}\n"
            f"  Duty Rate: {claim.duty_rate}\n"
            f"  Notes: {claim.notes or 'None'}"
            for claim in state.extracted_claims
        ])

        # Format prompt
        prompt = GENERATE_PROMPT.format(claims=claims_text)

        # Create messages for LLM
        messages = [
            LLMMessage(role="system", content="You are a tariff classification expert."),
            LLMMessage(role="user", content=prompt)
        ]

        # Generate report
        response = await self.llm.generate(
            messages=messages,
            model=get_tariff_llm_model(),
            temperature=0.5
        )

        report = response.content

        logger.info("report_generated", length=len(report))

        # Persist claims to DB if repository is available
        claim_ids: List[str] = []
        if self._claim_repo and state.workflow_run_id:
            for claim in state.extracted_claims:
                try:
                    db_claim = await self._claim_repo.create(
                        workflow_run_id=str(state.workflow_run_id),
                        claim_type="tariff_claim",
                        content=json.dumps({
                            "hs_code": claim.hs_code,
                            "description": claim.description,
                            "duty_rate": claim.duty_rate,
                            "notes": claim.notes,
                        }),
                        status="pending",
                        source_stage="generate",
                    )
                    claim_ids.append(str(db_claim.id))
                except Exception as exc:
                    logger.error("claim_persist_failed", error=str(exc))

        # Track which knowledge was actually adopted
        adopted_knowledge_entry_ids = []
        if state.prior_knowledge_entries:
            adopted_knowledge_entry_ids = self._identify_adopted_knowledge(
                state.prior_knowledge_entries,
                report
            )

        # Create lineage links for adopted knowledge only
        if self._lineage_link_repo and adopted_knowledge_entry_ids and claim_ids:
            lineage_links_created = 0
            for claim_id in claim_ids:
                for knowledge_entry_id in adopted_knowledge_entry_ids:
                    try:
                        await self._lineage_link_repo.create_link(
                            source_type="claim",
                            source_id=UUID(claim_id),
                            target_type="knowledge_entry",
                            target_id=UUID(knowledge_entry_id),
                            link_type="derived_from_knowledge",
                            workflow_run_id=UUID(state.workflow_run_id),
                            stage_name="generate",
                            metadata={"relevance": "high"}
                        )
                        lineage_links_created += 1
                    except Exception as exc:
                        logger.error("lineage_link_creation_failed", error=str(exc))

            if lineage_links_created > 0:
                logger.info("lineage_links_created", count=lineage_links_created)

        # Submit instruction to SuperDocs if enabled
        superdocs_job_id = None
        if (self._superdocs_client and
            self._instruction_builder and
            state.get("superdocs_session_id")):

            try:
                # Build instruction from extracted claims
                instruction = self._instruction_builder.build_tariff_instruction(
                    claims=state.extracted_claims
                )

                logger.info(
                    "submitting_superdocs_instruction",
                    session_id=state["superdocs_session_id"],
                    instruction_length=len(instruction)
                )

                # Submit async chat instruction with approval mode
                job = await self._superdocs_client.chat_async(
                    session_id=state["superdocs_session_id"],
                    message=instruction,
                    approval_mode="ask_every_time",  # HITL approval required
                    response_mode="compact"  # Token-efficient mode
                )

                superdocs_job_id = job.job_id

                logger.info(
                    "superdocs_instruction_submitted",
                    job_id=superdocs_job_id,
                    status=job.status.value
                )

            except Exception as exc:
                logger.error(
                    "superdocs_instruction_failed",
                    error=str(exc)
                )
                # Don't fail the workflow if SuperDocs fails
                # Just log and continue without SuperDocs job

        return {
            "generated_report": report,
            "generate_completed": True,
            "claim_ids": claim_ids,
            "adopted_knowledge_entry_ids": adopted_knowledge_entry_ids,
            "superdocs_job_id": superdocs_job_id,
        }
