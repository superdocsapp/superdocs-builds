"""
SuperDocs Instruction Builder.

Converts DocIntel workflow outputs into SuperDocs natural language instructions.
"""

from typing import List, Dict, Any
from dataclasses import dataclass

from backend.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class TariffClaim:
    """Tariff classification claim."""
    hs_code: str
    description: str
    duty_rate: str
    notes: str


@dataclass
class FormattingItem:
    """Screenplay formatting item."""
    line_start: int
    line_end: int
    element_type: str
    formatting: str


class InstructionBuilder:
    """
    Builds SuperDocs instructions from DocIntel outputs.

    Converts structured data (claims, formatting items) into natural language
    instructions that SuperDocs can execute via chat_async.
    """

    def build_tariff_instruction(
        self,
        claims: List[TariffClaim],
        report: str,
        target_section: str = "Classification Results"
    ) -> str:
        """
        Build SuperDocs instruction for tariff classification.

        Args:
            claims: List of tariff claims
            report: Generated classification report
            target_section: Target section name for insertion

        Returns:
            Natural language instruction for SuperDocs
        """
        logger.info("building_tariff_instruction", claims_count=len(claims))

        # Build instruction text
        instruction_parts = [
            f"Please update the document with the following tariff classification results:",
            "",
            "1. Create or update a section titled '{target_section}' with the following information:",
            ""
        ]

        # Add each claim
        for idx, claim in enumerate(claims, 1):
            instruction_parts.extend([
                f"**Classification {idx}:**",
                f"- HS Code: {claim.hs_code}",
                f"- Description: {claim.description}",
                f"- Duty Rate: {claim.duty_rate}",
            ])

            if claim.notes:
                instruction_parts.append(f"- Notes: {claim.notes}")

            instruction_parts.append("")

        # Add report if provided
        if report and report.strip():
            instruction_parts.extend([
                "2. Add the following detailed analysis:",
                "",
                report,
                ""
            ])

        instruction_parts.extend([
            "Please preserve all existing document formatting and structure.",
            "Only update or add the classification results section.",
            "Maintain professional business document formatting throughout."
        ])

        instruction = "\n".join(instruction_parts)

        logger.info(
            "tariff_instruction_built",
            instruction_length=len(instruction)
        )

        return instruction

    def build_screenplay_instruction(
        self,
        formatting_items: List[FormattingItem]
    ) -> str:
        """
        Build SuperDocs instruction for screenplay formatting.

        Args:
            formatting_items: List of formatting items

        Returns:
            Natural language instruction for SuperDocs
        """
        logger.info(
            "building_screenplay_instruction",
            items_count=len(formatting_items)
        )

        instruction_parts = [
            "Please apply the following screenplay formatting:",
            ""
        ]

        # Group by element type for clarity
        by_type: Dict[str, List[FormattingItem]] = {}
        for item in formatting_items:
            if item.element_type not in by_type:
                by_type[item.element_type] = []
            by_type[item.element_type].append(item)

        # Add instructions by type
        for element_type, items in by_type.items():
            instruction_parts.append(f"**{element_type.replace('_', ' ').title()}:**")

            for item in items:
                if item.line_start == item.line_end:
                    line_ref = f"Line {item.line_start}"
                else:
                    line_ref = f"Lines {item.line_start}-{item.line_end}"

                instruction_parts.append(
                    f"- {line_ref}: Apply {item.formatting} formatting"
                )

            instruction_parts.append("")

        instruction_parts.extend([
            "Please preserve all content exactly as written.",
            "Only change the formatting according to the specifications above.",
            "Maintain standard screenplay format conventions throughout."
        ])

        instruction = "\n".join(instruction_parts)

        logger.info(
            "screenplay_instruction_built",
            instruction_length=len(instruction)
        )

        return instruction

    def build_focused_update_instruction(
        self,
        changed_claims: List[TariffClaim],
        unchanged_claims: List[TariffClaim],
        report: str
    ) -> str:
        """
        Build instruction for focused update (only changed content).

        Args:
            changed_claims: Claims that changed
            unchanged_claims: Claims to preserve
            report: Updated analysis report

        Returns:
            Natural language instruction emphasizing preservation
        """
        logger.info(
            "building_focused_update_instruction",
            changed_count=len(changed_claims),
            unchanged_count=len(unchanged_claims)
        )

        instruction_parts = [
            "This is a focused update. Please make ONLY the following changes:",
            "",
            "**PRESERVE UNCHANGED (do not modify):**"
        ]

        # List what to preserve
        for claim in unchanged_claims:
            instruction_parts.append(f"- {claim.hs_code}: {claim.description}")

        instruction_parts.extend([
            "",
            "**UPDATE ONLY:**"
        ])

        # List what to change
        for idx, claim in enumerate(changed_claims, 1):
            instruction_parts.extend([
                f"{idx}. HS Code: {claim.hs_code}",
                f"   Description: {claim.description}",
                f"   Duty Rate: {claim.duty_rate}",
                ""
            ])

        if report:
            instruction_parts.extend([
                "**Updated Analysis:**",
                report,
                ""
            ])

        instruction_parts.extend([
            "CRITICAL: Do not modify any content marked as 'PRESERVE UNCHANGED'.",
            "Only update the specific items listed under 'UPDATE ONLY'.",
            "Maintain all existing document structure and formatting."
        ])

        instruction = "\n".join(instruction_parts)

        logger.info(
            "focused_update_instruction_built",
            instruction_length=len(instruction)
        )

        return instruction

    def build_generic_instruction(
        self,
        operation: str,
        content: str,
        constraints: List[str] = None
    ) -> str:
        """
        Build generic instruction for any operation.

        Args:
            operation: Description of operation to perform
            content: Content to insert/update
            constraints: Optional list of constraints

        Returns:
            Natural language instruction
        """
        instruction_parts = [
            operation,
            "",
            content
        ]

        if constraints:
            instruction_parts.extend(["", "**Constraints:**"])
            for constraint in constraints:
                instruction_parts.append(f"- {constraint}")

        return "\n".join(instruction_parts)

    def build_structured_memo_instruction(
        self,
        sections: List[Dict[str, Any]],
        image_refs: List[Dict[str, str]] = None,
        focused_update_preserve: List[str] = None,
    ) -> str:
        """Build clean, structured SuperDocs instruction from tariff memo sections.

        Sends a finalized document representation with explicit markdown section boundaries,
        eliminating redundant raw source attribution excerpts to reduce prompt bloat and
        diff fragmentation.
        """
        logger.info("building_structured_memo_instruction", sections_count=len(sections))

        parts = [
            "# Tariff Classification Memo",
            "",
            "Please update the document structure to present the finalized Tariff Classification Memo with the following sections:",
            "",
        ]

        if focused_update_preserve:
            parts.append("PRESERVE UNCHANGED (do not modify):")
            for item in focused_update_preserve:
                parts.append(f"- {item}")
            parts.append("")

        for section in sorted(sections, key=lambda s: s.get("section_order", 0)):
            title = section.get("title", "Section").strip()
            parts.append(f"## {title}")

            content_str = (section.get("content") or "").strip()
            reasoning_str = (section.get("analyst_reasoning") or "").strip()

            if content_str:
                parts.append(content_str)

            if (
                reasoning_str
                and reasoning_str.lower() != content_str.lower()
                and reasoning_str.lower() not in ("reasoning:", "reasoning", "analyst reasoning:", "analyst reasoning")
                and len(reasoning_str) >= 5
            ):
                parts.append(f"Analyst Reasoning: {reasoning_str}")
            parts.append("")

        if image_refs:
            parts.append("## Product Images")
            for img in image_refs:
                parts.append(f"- Embed {img.get('filename', 'image')} (document_id: {img.get('document_id', '')})")
            parts.append("")

        parts.extend([
            "FORMATTING GUIDELINES:",
            "- Maintain professional document formatting throughout.",
            "- Preserve section boundaries as delineated by the headers.",
        ])

        instruction = "\n".join(parts)
        logger.info("structured_memo_instruction_built", instruction_length=len(instruction))
        return instruction
