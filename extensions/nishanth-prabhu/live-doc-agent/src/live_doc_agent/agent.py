"""Live Doc Agent coordinating wiki synchronization with SuperDocs and human approval."""

from __future__ import annotations

import re
from typing import Callable, List, Optional
from live_doc_agent.models import (
    ChangeDecision,
    ConflictError,
    LiveDocAgentError,
    Patch,
    PromptInjectionDetected,
    ProposedChange,
    RunResult,
    RunStatus,
    WikiDocument,
)
from live_doc_agent.patcher import DocumentPatcher
from live_doc_agent.superdocs.client import SuperDocsClient
from live_doc_agent.wiki.base import WikiAdapter

# Common prompt injection triggers to guard against malicious decisions
_INJECTION_PATTERNS = [
    r"(?i)ignore\s+(all\s+)?(previous|prior)\s+instructions",
    r"(?i)system\s*override",
    r"(?i)delete\s+(the\s+)?entire\s+(document|page|wiki)",
    r"(?i)disregard\s+(the\s+)?(above|system)",
    r"(?i)you\s+are\s+now\s+in\s+developer\s+mode",
]


class LiveDocAgent:
    """Orchestrates surgical document updates with SuperDocs and Human Approval."""

    def __init__(
        self,
        wiki_adapter: WikiAdapter,
        superdocs_client: SuperDocsClient,
    ) -> None:
        self.wiki = wiki_adapter
        self.superdocs = superdocs_client

    def check_safety(self, decision_text: str) -> None:
        """Inspect decision text for prompt injection and adversarial commands."""
        for pattern in _INJECTION_PATTERNS:
            if re.search(pattern, decision_text):
                raise PromptInjectionDetected(
                    f"Potential prompt injection detected matching pattern: {pattern}"
                )

    def run(
        self,
        doc_id: str,
        decision_text: str,
        approval_gate: Optional[
            Callable[[WikiDocument, List[ProposedChange]], List[ChangeDecision]]
        ] = None,
        auto_approve: bool = False,
    ) -> RunResult:
        """Execute one complete synchronization cycle.

        1. Input safety verification
        2. Fetch wiki document snapshot (with error boundary)
        3. SuperDocs chat analysis to propose surgical changes
        4. Validate proposals (target section, unique old snippet, confidence, duplicate IDs)
        5. No-op short-circuit if no stale sections
        6. Human Approval Gate
        7. Record approved changes in SuperDocs session
        8. Apply surgical patches via wiki adapter
        9. Verify untouched sections invariant
        """
        # 1. Safety check
        try:
            self.check_safety(decision_text)
        except PromptInjectionDetected as err:
            return RunResult(
                status=RunStatus.ERROR,
                decision_summary=decision_text,
                error_message=str(err),
            )

        # 2. Fetch current wiki page
        try:
            before_doc = self.wiki.fetch_page(doc_id)
        except Exception as err:
            return RunResult(
                status=RunStatus.ERROR,
                decision_summary=decision_text,
                error_message=f"Failed to fetch wiki document '{doc_id}': {err}",
            )

        # 3. SuperDocs upload snapshot & chat query
        chat_prompt = (
            f"A new company/team decision has been made:\n"
            f"\"\"\"\n{decision_text}\n\"\"\"\n\n"
            f"Analyze the document content below. If this decision contradicts or updates any "
            f"existing section, propose surgical edits for ONLY the stale paragraphs. "
            f"Do not rewrite the entire page or touch unaffected sections.\n"
            f"Current Document:\n{before_doc.content}"
        )

        try:
            superdocs_doc_id = self.superdocs.upload(
                title=before_doc.title,
                content=before_doc.content,
            )
            proposed_changes = self.superdocs.chat(
                doc_id=superdocs_doc_id,
                prompt=chat_prompt,
            )
        except Exception as err:
            return RunResult(
                status=RunStatus.ERROR,
                decision_summary=decision_text,
                before_document=before_doc,
                error_message=f"SuperDocs interaction failed: {err}",
            )

        # 4. No-op verification
        if not proposed_changes:
            return RunResult(
                status=RunStatus.NOOP,
                decision_summary=decision_text,
                proposed_changes=[],
                before_document=before_doc,
                after_document=before_doc,
            )

        # 5. Validate proposed changes before presenting to human gate
        change_ids = [c.change_id for c in proposed_changes]
        if len(change_ids) != len(set(change_ids)):
            return RunResult(
                status=RunStatus.VALIDATION_FAILED,
                decision_summary=decision_text,
                proposed_changes=proposed_changes,
                before_document=before_doc,
                after_document=before_doc,
                error_message="Duplicate change IDs returned by SuperDocs.",
            )

        for change in proposed_changes:
            try:
                DocumentPatcher.validate_proposal(before_doc, change)
            except LiveDocAgentError as val_err:
                return RunResult(
                    status=RunStatus.VALIDATION_FAILED,
                    decision_summary=decision_text,
                    proposed_changes=proposed_changes,
                    before_document=before_doc,
                    after_document=before_doc,
                    error_message=f"Proposal validation failed for change '{change.change_id}': {val_err}",
                )

        # 6. Human Approval Gate
        decisions: List[ChangeDecision] = []
        try:
            if approval_gate:
                decisions = approval_gate(before_doc, proposed_changes)
            elif auto_approve:
                decisions = [
                    ChangeDecision(change_id=c.change_id, approved=True)
                    for c in proposed_changes
                ]
            else:
                decisions = [
                    ChangeDecision(
                        change_id=c.change_id,
                        approved=False,
                        rejection_reason="No approval gate provided",
                    )
                    for c in proposed_changes
                ]
        except Exception as err:
            return RunResult(
                status=RunStatus.ERROR,
                decision_summary=decision_text,
                proposed_changes=proposed_changes,
                before_document=before_doc,
                after_document=before_doc,
                error_message=f"Approval gate failed: {err}",
            )

        decision_map = {d.change_id: d for d in decisions}
        approved_changes = [
            c for c in proposed_changes
            if decision_map.get(c.change_id) and decision_map[c.change_id].approved
        ]

        if not approved_changes:
            return RunResult(
                status=RunStatus.REJECTED,
                decision_summary=decision_text,
                proposed_changes=proposed_changes,
                decisions=decisions,
                before_document=before_doc,
                after_document=before_doc,
            )

        # 7. Record approval in SuperDocs session
        try:
            self.superdocs.approve(
                superdocs_doc_id,
                [c.change_id for c in approved_changes],
            )
        except Exception as err:
            return RunResult(
                status=RunStatus.ERROR,
                decision_summary=decision_text,
                proposed_changes=proposed_changes,
                decisions=decisions,
                before_document=before_doc,
                after_document=before_doc,
                error_message=f"Failed to record approval in SuperDocs: {err}",
            )

        # 8. Apply surgical patches to wiki
        applied_patches: List[Patch] = []
        current_doc = before_doc

        for change in approved_changes:
            decision = decision_map[change.change_id]
            replacement_text = (
                decision.user_override_text
                if decision.user_override_text is not None
                else change.new_snippet
            )

            patch = Patch(
                patch_id=f"patch_{change.change_id}",
                target_section=change.target_section,
                original_snippet=change.old_snippet,
                replacement_snippet=replacement_text,
                expected_version=current_doc.content_version,
            )

            try:
                current_doc = self.wiki.apply_patch(doc_id, patch)
                applied_patches.append(patch)
            except ConflictError as conf_err:
                return RunResult(
                    status=RunStatus.CONFLICT,
                    decision_summary=decision_text,
                    proposed_changes=proposed_changes,
                    decisions=decisions,
                    applied_patches=applied_patches,
                    before_document=before_doc,
                    after_document=current_doc,
                    error_message=str(conf_err),
                )
            except Exception as err:
                return RunResult(
                    status=RunStatus.ERROR,
                    decision_summary=decision_text,
                    proposed_changes=proposed_changes,
                    decisions=decisions,
                    applied_patches=applied_patches,
                    before_document=before_doc,
                    after_document=current_doc,
                    error_message=str(err),
                )

        # 9. Invariant check: unaffected sections must remain identical
        modified_sections = [p.target_section for p in applied_patches]
        invariant_met = DocumentPatcher.verify_untouched_invariant(
            before_doc.content, current_doc.content, modified_sections
        )
        if not invariant_met:
            return RunResult(
                status=RunStatus.ERROR,
                decision_summary=decision_text,
                proposed_changes=proposed_changes,
                decisions=decisions,
                applied_patches=applied_patches,
                before_document=before_doc,
                after_document=current_doc,
                error_message="Invariant violation: Unrelated sections were modified!",
            )

        return RunResult(
            status=RunStatus.APPLIED,
            decision_summary=decision_text,
            proposed_changes=proposed_changes,
            decisions=decisions,
            applied_patches=applied_patches,
            before_document=before_doc,
            after_document=current_doc,
        )
