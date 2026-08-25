"""In-place Section Boundary Replacement Engine.

Targets updates exclusively to designated section anchors (e.g. evaluation section
and timestamp anchors). All human-written narrative text outside the anchors
remains 100% untouched during updates.
"""

from __future__ import annotations

from datetime import datetime, timezone
import re
from pathlib import Path
from typing import Optional, Tuple, Union


class AnchorError(Exception):
    """Base exception for section anchor boundary errors."""
    pass


class AnchorNotFoundError(AnchorError):
    """Raised when an anchor marker is not found in document."""
    pass


class CorruptedAnchorError(AnchorError):
    """Raised when start and end anchors are misaligned or duplicate."""
    pass


# Default boundary markers
EVAL_SECTION_START = "<!-- EVALUATION_SECTION_START -->"
EVAL_SECTION_END = "<!-- EVALUATION_SECTION_END -->"

EVAL_TIMESTAMP_START = "<!-- EVALUATION_TIMESTAMP_START -->"
EVAL_TIMESTAMP_END = "<!-- EVALUATION_TIMESTAMP_END -->"


class SectionBoundaryUpdater:
    """Safely updates specific delimited sections in Markdown documents without touching other text."""

    @staticmethod
    def replace_boundary_content(
        content: str,
        start_anchor: str,
        end_anchor: str,
        replacement_text: str,
        preserve_anchors: bool = True
    ) -> str:
        """Replace content strictly between start_anchor and end_anchor.
        
        Args:
            content: Full document text
            start_anchor: The opening comment anchor
            end_anchor: The closing comment anchor
            replacement_text: The new content to place between anchors
            preserve_anchors: Whether to keep the anchor tags in the result
            
        Returns:
            Updated document content with anchors and new text in place.
        """
        start_count = content.count(start_anchor)
        end_count = content.count(end_anchor)

        if start_count == 0:
            raise AnchorNotFoundError(f"Start anchor not found in document: {start_anchor}")
        if end_count == 0:
            raise AnchorNotFoundError(f"End anchor not found in document: {end_anchor}")
        if start_count > 1 or end_count > 1:
            raise CorruptedAnchorError(
                f"Multiple instances of anchors detected (start: {start_count}, end: {end_count})"
            )

        start_pos = content.find(start_anchor)
        end_pos = content.find(end_anchor)

        if start_pos >= end_pos:
            raise CorruptedAnchorError(
                f"Anchor positioning corrupted: start_anchor occurs after end_anchor."
            )

        # Content before start anchor
        before = content[: start_pos + (len(start_anchor) if preserve_anchors else 0)]
        # Content after end anchor
        after = content[end_pos if preserve_anchors else (end_pos + len(end_anchor)) :]

        # Standardize spacing around replacement text
        clean_rep = replacement_text.strip()
        if preserve_anchors:
            clean_rep = f"\n{clean_rep}\n"

        return f"{before}{clean_rep}{after}"

    @classmethod
    def update_evaluation(
        cls,
        document_content: str,
        new_eval_markdown: str,
        timestamp: Optional[str] = None,
        run_id: Optional[str] = None,
        baseline_model: Optional[str] = None,
    ) -> str:
        """Perform targeted update on evaluation table and timestamp anchors.
        
        Leaves all other markdown content (executive summary, limitations, ethics, etc.)
        strictly 100% untouched.
        """
        updated = document_content

        # Update evaluation table section
        updated = cls.replace_boundary_content(
            content=updated,
            start_anchor=EVAL_SECTION_START,
            end_anchor=EVAL_SECTION_END,
            replacement_text=new_eval_markdown
        )

        # Update timestamp metadata section if timestamp anchors exist
        if EVAL_TIMESTAMP_START in updated and EVAL_TIMESTAMP_END in updated:
            ts_str = timestamp or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            run_id_str = run_id or f"run-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
            baseline_str = baseline_model or "Not specified"

            timestamp_block = (
                f"- **Last Updated**: {ts_str}\n"
                f"- **Evaluation Run ID**: `{run_id_str}`\n"
                f"- **Baseline Reference**: {baseline_str}"
            )

            updated = cls.replace_boundary_content(
                content=updated,
                start_anchor=EVAL_TIMESTAMP_START,
                end_anchor=EVAL_TIMESTAMP_END,
                replacement_text=timestamp_block
            )

        return updated

    @classmethod
    def update_file_in_place(
        cls,
        card_file_path: Union[str, Path],
        new_eval_markdown: str,
        timestamp: Optional[str] = None,
        run_id: Optional[str] = None,
        baseline_model: Optional[str] = None,
    ) -> Tuple[str, bool]:
        """Read existing file, apply in-place evaluation update, and rewrite file safely.
        
        Returns:
            (updated_content, is_modified)
        """
        path = Path(card_file_path)
        if not path.is_file():
            raise FileNotFoundError(f"Model card file not found: {card_file_path}")

        with open(path, "r", encoding="utf-8") as f:
            original_content = f.read()

        updated_content = cls.update_evaluation(
            document_content=original_content,
            new_eval_markdown=new_eval_markdown,
            timestamp=timestamp,
            run_id=run_id,
            baseline_model=baseline_model
        )

        # Only write if content actually changed
        is_modified = updated_content != original_content
        if is_modified:
            with open(path, "w", encoding="utf-8") as f:
                f.write(updated_content)

        return updated_content, is_modified
