"""
Handles "adaptations regenerate when the source chapter is revised" without the strong-vs-competent failure
mode the task card calls out: "a source revision regenerates adaptations without discarding teacher edits
already made to them."

The mechanism: diff the revised source's chunks against the previous source's chunks by (chunk_id, hash).
Only chunks whose source content actually changed are candidates for re-adaptation. Of those, any chunk id
in `locked_chunk_ids` (chunks a teacher has since hand-edited in the adaptation -- tracked by whatever
calling app owns that bookkeeping, not this module) is skipped even though its source changed, and reported
separately so the caller can decide (merge conflict UI, notify the teacher, etc.) rather than silently
overwriting their edit or silently ignoring the source change.
"""
from __future__ import annotations

from dataclasses import dataclass

from src.adaptation import AdaptationResult, AdaptationType, run_adaptation
from src.chunk_classifier import classify_document


@dataclass
class RevisionPlan:
    changed_chunk_ids: list[str]
    unchanged_chunk_ids: list[str]
    locked_and_skipped_chunk_ids: list[str]  # changed in source, but teacher-edited -> deliberately not touched
    needs_regeneration: bool


def plan_revision(previous_source_html: str, revised_source_html: str, locked_chunk_ids: set[str]) -> RevisionPlan:
    previous_chunks = {c.chunk_id: c.content_hash for c in classify_document(previous_source_html)}
    revised_chunks = {c.chunk_id: c.content_hash for c in classify_document(revised_source_html)}

    changed = []
    unchanged = []
    locked_and_skipped = []
    for chunk_id, revised_hash in revised_chunks.items():
        previous_hash = previous_chunks.get(chunk_id)
        if previous_hash != revised_hash:
            if chunk_id in locked_chunk_ids:
                locked_and_skipped.append(chunk_id)
            else:
                changed.append(chunk_id)
        else:
            unchanged.append(chunk_id)

    return RevisionPlan(
        changed_chunk_ids=changed, unchanged_chunk_ids=unchanged,
        locked_and_skipped_chunk_ids=locked_and_skipped, needs_regeneration=bool(changed),
    )


def apply_revision(
    client, source_session_id: str, revised_source_html: str, adaptation_type: AdaptationType,
    plan: RevisionPlan, terminology_map: str = "",
) -> AdaptationResult | None:
    """Re-runs adaptation ONLY if something actually needs it (an update should 'cost like an update' --
    Task 1's own principle, applied here too: no LLM call at all if plan.needs_regeneration is False)."""
    if not plan.needs_regeneration:
        return None
    return run_adaptation(
        client, source_session_id, revised_source_html, adaptation_type,
        terminology_map=terminology_map, session_suffix="__rev",
    )
