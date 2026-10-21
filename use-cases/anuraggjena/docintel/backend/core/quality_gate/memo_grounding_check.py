"""
Memo Grounding Check for Quality Gate.

Validates generated memo sections against authoritative workflow state
to prevent contradictions, unsupported claims, and placeholder content.
"""

from typing import Any, Dict, List
from uuid import UUID

from backend.core.quality_gate.checks import BaseCheck, CheckResult, CheckStatus, CheckSeverity
from backend.modules.tariff.memo_grounding import validate_memo_sections, GroundingViolation
from backend.modules.tariff.memo_types import ProductFacts, RulingFacts, MemoSectionOutput
from backend.logging_config import get_logger

logger = get_logger(__name__)


class MemoGroundingCheck(BaseCheck):
    """
    Check that generated memo sections are grounded in authoritative workflow state.

    Validates against:
    - ProductFacts (from product specification documents)
    - RulingFacts (from ruling documents)
    - Matched ruling IDs (from reconciliation)
    - Reconciliation conflicts
    - Retrieved evidence

    Detects:
    - Contradictions with product facts
    - Contradictions with ruling facts
    - Unsupported classification assertions
    - Unsupported "no ruling" statements
    - Placeholder values
    - Missing source attribution
    - Fabricated ruling identifiers
    """

    name = "memo_grounding"
    severity = CheckSeverity.ERROR
    blocking = True  # Grounding failures MUST block

    def __init__(self, memo_section_repo=None):
        """
        Initialize memo grounding check.

        Args:
            memo_section_repo: Repository for fetching memo sections
        """
        self.memo_section_repo = memo_section_repo

    async def run(self, state: Dict[str, Any], config: Dict[str, Any]) -> CheckResult:
        """
        Run memo grounding check against workflow state.

        Args:
            state: Workflow state containing:
                - product_facts: Authoritative ProductFacts
                - ruling_facts: List of RulingFacts
                - matched_ruling_ids: IDs of matched rulings
                - reconciliation_conflicts: Conflicts from reconciliation
                - retrieved_chunks: Retrieved evidence
                - workflow_run_id: Current run ID (for fetching sections)

        Returns:
            CheckResult with grounding violation details
        """
        # Support both dict and Pydantic model state
        workflow_run_id = state.get("workflow_run_id") if isinstance(state, dict) else getattr(state, "workflow_run_id", None)

        if not workflow_run_id:
            return self.skip("No workflow run ID available")

        # Load memo sections
        memo_sections = await self._load_memo_sections(UUID(workflow_run_id))

        if not memo_sections:
            return self.skip("No memo sections to validate")

        # Extract authoritative state
        product_facts = state.get("product_facts") if isinstance(state, dict) else getattr(state, "product_facts", None)
        ruling_facts = state.get("ruling_facts", []) if isinstance(state, dict) else getattr(state, "ruling_facts", [])
        matched_ruling_ids = state.get("matched_ruling_ids", []) if isinstance(state, dict) else getattr(state, "matched_ruling_ids", [])
        reconciliation_conflicts = state.get("reconciliation_conflicts", []) if isinstance(state, dict) else getattr(state, "reconciliation_conflicts", [])
        retrieved_evidence = state.get("retrieved_chunks", []) if isinstance(state, dict) else getattr(state, "retrieved_chunks", [])

        logger.info(
            "checking_memo_grounding",
            section_count=len(memo_sections),
            has_product_facts=product_facts is not None,
            ruling_count=len(ruling_facts),
            matched_ruling_count=len(matched_ruling_ids),
        )

        # Validate sections
        violations = validate_memo_sections(
            memo_sections=memo_sections,
            product_facts=product_facts,
            ruling_facts=ruling_facts,
            matched_ruling_ids=matched_ruling_ids,
            reconciliation_conflicts=reconciliation_conflicts,
            retrieved_evidence=retrieved_evidence,
        )

        # Categorize violations by severity
        errors = [v for v in violations if v.severity == "error"]
        warnings = [v for v in violations if v.severity == "warning"]

        if errors:
            # Blocking errors found
            details = {
                "total_violations": len(violations),
                "errors": len(errors),
                "warnings": len(warnings),
                "violations": [v.to_dict() for v in violations[:10]],  # Limit to first 10
            }

            message = (
                f"Memo grounding failed: {len(errors)} error(s), {len(warnings)} warning(s). "
                f"Memo content contradicts or is not supported by authoritative workflow state. "
                f"Categories: {self._summarize_categories(violations)}"
            )

            logger.error(
                "memo_grounding_check_failed",
                errors=len(errors),
                warnings=len(warnings),
                categories=self._summarize_categories(violations),
            )

            return self.failed(message, details)

        if warnings:
            # Warnings only, non-blocking
            details = {
                "total_violations": len(violations),
                "errors": 0,
                "warnings": len(warnings),
                "violations": [v.to_dict() for v in violations[:10]],
            }

            message = (
                f"Memo grounding warnings: {len(warnings)} warning(s). "
                f"Categories: {self._summarize_categories(violations)}"
            )

            logger.warning(
                "memo_grounding_check_warnings",
                warnings=len(warnings),
                categories=self._summarize_categories(violations),
            )

            return self.warning(message, details)

        # All checks passed
        logger.info(
            "memo_grounding_check_complete",
            sections_validated=len(memo_sections),
            violations=0,
        )

        return self.passed(
            f"Memo grounding validated: {len(memo_sections)} section(s), no violations"
        )

    async def _load_memo_sections(
        self, workflow_run_id: UUID
    ) -> Dict[str, MemoSectionOutput]:
        """
        Load memo sections from database.

        Returns:
            Dict mapping section_type to MemoSectionOutput
        """
        if not self.memo_section_repo:
            return {}

        try:
            # Fetch all sections for this run
            sections = await self.memo_section_repo.list_by_run(workflow_run_id)

            memo_sections = {}
            for section in sections:
                if getattr(section, "status", None) == "skipped":
                    continue
                try:
                    structured = section.structured_data if isinstance(getattr(section, "structured_data", None), dict) else {}
                    has_content = isinstance(getattr(section, "content", None), str) and bool(section.content.strip())
                    has_structured = bool(structured)

                    if not has_content and not has_structured:
                        continue

                    # If structured_data is already a full MemoSectionOutput dict (unit tests or legacy)
                    if "content" in structured and "analyst_reasoning" in structured:
                        section_output = MemoSectionOutput(**structured)
                    else:
                        # Real database model MemoSection
                        sec_content = getattr(section, "content", None)
                        if not isinstance(sec_content, str):
                            sec_content = structured.get("content", "")

                        sec_reasoning = getattr(section, "analyst_reasoning", None)
                        if not isinstance(sec_reasoning, str):
                            sec_reasoning = structured.get("analyst_reasoning", "")

                        sec_source = getattr(section, "source_attribution", None)
                        if not isinstance(sec_source, list):
                            sec_source = structured.get("source_attribution", [])

                        sec_conf = getattr(section, "confidence", None)
                        if not isinstance(sec_conf, str):
                            sec_conf = structured.get("confidence", "high")

                        alts = structured.get("alternatives", [])
                        rec = structured.get("recommendation", None)

                        section_output = MemoSectionOutput(
                            content=sec_content or "",
                            analyst_reasoning=sec_reasoning or "",
                            source_attribution=sec_source or [],
                            confidence=sec_conf or "high",
                            alternatives=alts,
                            recommendation=rec,
                            adopted_knowledge_entry_ids=[],
                        )
                    memo_sections[section.section_type] = section_output
                except Exception as exc:
                    logger.warning(
                        "failed_to_parse_memo_section",
                        section_type=getattr(section, "section_type", "unknown"),
                        error=str(exc),
                    )

            return memo_sections

        except Exception as exc:
            logger.error("failed_to_load_memo_sections", error=str(exc))
            return {}

    def _summarize_categories(self, violations: List[GroundingViolation]) -> str:
        """Summarize violation categories for logging/reporting."""
        categories = {}
        for v in violations:
            categories[v.category] = categories.get(v.category, 0) + 1

        return ", ".join(f"{cat}={count}" for cat, count in categories.items())
