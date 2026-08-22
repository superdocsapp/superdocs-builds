"""
Ties code_diff.py and doc_index.py together into proposed doc updates, then (once a human approves) applies
them via SuperDocs chat, scoped to exactly the chunk(s) that reference the changed function -- never a
whole-document rewrite.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

from src.code_diff import FunctionChange
from src.doc_index import DocChunk, find_doc_references

ProposalKind = Literal["update_doc_section", "flag_undocumented", "propose_removal"]


@dataclass
class DocSyncProposal:
    function_change: FunctionChange
    kind: ProposalKind
    target_chunks: list[DocChunk]  # empty for flag_undocumented
    instruction: Optional[str]  # None for flag_undocumented -- there's nothing to scope an edit to yet
    citation: str  # file:line the proposal is grounded in

    def summary(self) -> str:
        if self.kind == "flag_undocumented":
            return f"⚠ UNDOCUMENTED: {self.function_change.describe()} (cite: {self.citation}) -- no doc section mentions `{self.function_change.name}`"
        chunk_ids = ", ".join(c.chunk_id for c in self.target_chunks)
        return f"✎ PROPOSED UPDATE to chunk(s) [{chunk_ids}]: {self.function_change.describe()} (cite: {self.citation})"


def build_proposals(changes: list[FunctionChange], doc_chunks: list[DocChunk]) -> list[DocSyncProposal]:
    """For every code change, decides what (if anything) should happen to the docs. This is the core
    'never propose without a real reason' logic:
      - a function whose signature changed AND is documented somewhere -> propose a scoped edit
      - a function whose signature changed but ISN'T documented anywhere -> flag it, don't silently drop it
        or silently invent a new doc section without a human deciding that's wanted
      - a function that was removed AND is documented -> propose removing that doc section
      - docstring-only changes are still proposed (the doc might quote the docstring) but are lower-signal;
        included for completeness, not treated specially
    """
    proposals = []
    for change in changes:
        hits = find_doc_references(doc_chunks, change.name)

        if change.change_type == "removed":
            if hits:
                proposals.append(DocSyncProposal(
                    function_change=change, kind="propose_removal", target_chunks=hits,
                    instruction=(
                        f"The function `{change.name}` has been removed from the codebase "
                        f"(it used to be: `{change.old.signature}`). Update or remove the documentation "
                        f"for it in this section so the docs don't describe a function that no longer "
                        f"exists. Only touch this section."
                    ),
                    citation=change.citation(),
                ))
            # If removed AND never documented, there's nothing to do -- not even worth flagging.
            continue

        if not hits:
            proposals.append(DocSyncProposal(
                function_change=change, kind="flag_undocumented", target_chunks=[],
                instruction=None, citation=change.citation(),
            ))
            continue

        proposals.append(DocSyncProposal(
            function_change=change, kind="update_doc_section", target_chunks=hits,
            instruction=(
                f"{change.describe()}. Update ONLY this section so it accurately reflects the current "
                f"function signature. Do not change any other part of the document."
            ),
            citation=change.citation(),
        ))

    return proposals


def apply_approved_updates(client, session_id: str, doc_html: str, approved: list[DocSyncProposal]) -> dict[str, str]:
    """Applies each approved proposal as its own scoped chat turn against the SAME session (so each edit
    sees the result of prior approved edits), skipping flag_undocumented proposals entirely -- there is no
    edit to apply for those, only a human decision to (separately, manually) go write new docs.

    Returns {citation: ai_response_text} for a simple audit trail of what was applied for what reason.
    """
    results = {}
    current_html = doc_html
    for proposal in approved:
        if proposal.kind == "flag_undocumented":
            continue
        response = client.chat(session_id=session_id, message=proposal.instruction, document_html=current_html)
        current_html = response["document_changes"]["updated_html"]
        results[proposal.citation] = response.get("response", "")
    return results
