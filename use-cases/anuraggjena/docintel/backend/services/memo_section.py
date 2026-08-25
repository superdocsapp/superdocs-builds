import json
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from backend.models.claim import Claim
from backend.models.memo_section import MemoSection
from backend.repositories.memo_section import MemoSectionRepository
from backend.repositories.review import ClaimRepository
from backend.logging_config import get_logger

logger = get_logger(__name__)


class MemoSectionService:
    def __init__(
        self,
        section_repo: MemoSectionRepository,
        claim_repo: ClaimRepository,
    ):
        self._section_repo = section_repo
        self._claim_repo = claim_repo

    async def create_section_with_claim(
        self,
        workflow_run_id: UUID,
        section_type: str,
        title: str,
        section_order: int,
        content: str,
        analyst_reasoning: Optional[str] = None,
        source_attribution: Optional[List[Dict[str, Any]]] = None,
        evidence_refs: Optional[List[str]] = None,
        confidence: Optional[str] = None,
        structured_data: Optional[Dict[str, Any]] = None,
        baseline_section_id: Optional[UUID] = None,
        status: str = "pending",
    ) -> Tuple[MemoSection, Claim]:
        section = await self._section_repo.create(
            workflow_run_id=workflow_run_id,
            section_type=section_type,
            title=title,
            section_order=section_order,
            content=content,
            status=status,
            analyst_reasoning=analyst_reasoning,
            source_attribution=source_attribution or [],
            evidence_refs=evidence_refs or [],
            confidence=confidence,
            structured_data=structured_data,
            baseline_section_id=baseline_section_id,
        )
        claim = await self._claim_repo.create(
            workflow_run_id=str(workflow_run_id),
            claim_type="memo_section",
            content=json.dumps({
                "memo_section_id": str(section.id),
                "section_type": section_type,
                "title": title,
                "section_order": section_order,
                "content": content,
                "new_html": content,
                "old_html": None,
                "content_preview": content[:500],
                "analyst_reasoning": analyst_reasoning,
                "ai_explanation": analyst_reasoning,
                "confidence": confidence,
                "baseline_section_id": str(baseline_section_id) if baseline_section_id else None,
            }),
            status="pending",
            source_stage="generate_memo_sections",
        )
        logger.info("memo_section_created", section_id=str(section.id), claim_id=str(claim.id))
        return section, claim

    async def copy_section_from_baseline(
        self,
        baseline_section: MemoSection,
        new_run_id: UUID,
    ) -> Tuple[MemoSection, Claim]:
        return await self.create_section_with_claim(
            workflow_run_id=new_run_id,
            section_type=baseline_section.section_type,
            title=baseline_section.title,
            section_order=baseline_section.section_order,
            content=baseline_section.content,
            analyst_reasoning=baseline_section.analyst_reasoning,
            source_attribution=baseline_section.source_attribution,
            evidence_refs=baseline_section.evidence_refs,
            confidence=baseline_section.confidence,
            structured_data=baseline_section.structured_data,
            baseline_section_id=baseline_section.id,
            status=baseline_section.status if baseline_section.status == "approved" else "pending",
        )
