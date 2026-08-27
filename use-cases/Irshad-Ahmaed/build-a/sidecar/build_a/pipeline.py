"""Revision apparatus pipeline — end-to-end orchestration.

Connects the SuperDocs client, doc-diff engine, and revision apparatus
generator into a single callable pipeline. Handles document loading,
editing, diffing, apparatus injection, and operation budget tracking.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from .apparatus import RevisionApparatus, RevisionMetadata
from .client import SuperDocsClient, SuperDocsError
from .differ import DiffResult, DocDiffer

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    """Result of a full revision pipeline run."""

    session_id: str
    diff: DiffResult
    apparatus_instructions: list[str] = field(default_factory=list)
    apparatus_responses: list[dict[str, Any]] = field(default_factory=list)
    ops_used: int = 0
    errors: list[str] = field(default_factory=list)
    post_edit_html: str = ""

    @property
    def success(self) -> bool:
        return len(self.errors) == 0


class RevisionPipeline:
    """Orchestrates the full revision apparatus flow.

    Connects: SuperDocsClient → edit → diff → apparatus injection.

    Usage:
        async with SuperDocsClient() as client:
            pipeline = RevisionPipeline(client)
            result = await pipeline.run(
                document_html=html,
                session_id="revision-0042",
                edit_instructions="Update section 4.2...",
                metadata=RevisionMetadata(...),
            )
    """

    def __init__(self, client: SuperDocsClient) -> None:
        self.client = client
        self.differ = DocDiffer()
        self.apparatus = RevisionApparatus()

    async def run(
        self,
        document_html: str,
        session_id: str,
        edit_instructions: str,
        metadata: RevisionMetadata,
    ) -> PipelineResult:
        """Run the full revision flow.

        Steps:
        1. Start session + load document + apply edit (1 op — combined)
        2. Diff pre-edit vs post-edit HTML (0 ops — local)
        3. Generate and send apparatus instructions (1 op per batch)

        Args:
            document_html: The prior revision's HTML to load.
            session_id: User-chosen session identifier.
            edit_instructions: Natural language edit instructions.
            metadata: Revision metadata (number, date, changes).
        """
        result = PipelineResult(session_id=session_id, diff=DiffResult(
            changed=[], total_paragraphs_old=0, total_paragraphs_new=0,
        ))

        # Step 1: Start session + load + apply edit in single call (1 op)
        pre_edit_html = document_html
        try:
            edit_result_resp = await self.client.start_session(
                document_html, session_id, message=edit_instructions,
            )
            edit_result = edit_result_resp.model_dump()
        except SuperDocsError as e:
            result.errors.append(f"Step 1 (load+edit): {e}")
            return result

        # Step 2: Get post-edit HTML
        post_edit_html = await self._get_post_edit_html(session_id, edit_result)
        result.post_edit_html = post_edit_html

        # Step 3: Diff
        result.diff = self.differ.diff(pre_edit_html, post_edit_html)
        logger.info(
            "Diff: %d changed paragraphs out of %d old / %d new",
            len(result.diff.changed),
            result.diff.total_paragraphs_old,
            result.diff.total_paragraphs_new,
        )

        if not result.diff.has_changes:
            logger.info("No changes detected — skipping apparatus injection")
            result.ops_used = self.client.tracker.total_ops
            return result

        # Step 4-5: Generate and send apparatus instructions
        instructions = self.apparatus.generate_combined(result.diff, metadata)
        result.apparatus_instructions = instructions

        for instruction in instructions:
            try:
                resp = await self.client.edit(instruction, session_id)
                result.apparatus_responses.append(resp.model_dump())
            except SuperDocsError as e:
                result.errors.append(f"Apparatus injection: {e}")

        result.ops_used = self.client.tracker.total_ops
        return result

    async def _get_post_edit_html(
        self, session_id: str, edit_response: dict[str, Any]
    ) -> str:
        """Get post-edit HTML from edit response or session history."""
        # Try to get from edit response first
        doc_changes = edit_response.get("document_changes") or edit_response
        updated = doc_changes.get("updated_html") if isinstance(doc_changes, dict) else None
        if updated:
            return updated

        # Fallback: fetch from session history (0 ops)
        # document_html is a property that extracts from document_state.html_content
        try:
            history = await self.client.get_session_history(session_id)
            if history.document_html:
                return history.document_html
        except SuperDocsError as exc:
            logger.warning("Failed to fetch session history for post-edit HTML: %s", exc)

        return ""  # worst case: empty, diff will show everything as added
