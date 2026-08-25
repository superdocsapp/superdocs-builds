"""
@file: backend/agents/state.py
@description: The state object threaded through every node of the digest graph. Kept
    deliberately small and JSON-serialisable: bulk data (conversation text, embeddings,
    theme rows) lives in Postgres and is referenced by run_id, so a checkpoint write is
    cheap and a resumed run rehydrates from the database rather than from a fat blob.
@flow: build_initial_state() at run start -> each node reads what it needs, writes its
    summary fields, and returns the mutated dict -> LangGraph carries it forward ->
    serialised into runs.checkpoint_data at each stage boundary.
@dependencies:
    - typing.TypedDict: LangGraph's expected state shape
"""

from __future__ import annotations

import uuid
from typing import Any, Literal, TypedDict

# Canonical stage names. These are the checkpoint keys, the RunStatus mapping, and the
# labels the frontend timeline renders — one source of truth for all three.
STAGES: tuple[str, ...] = (
    "ingest",
    "classify",
    "extract",
    "theme",
    "anonymize",
    "compare",
    "draft",
    "human_gate",
    "superdocs",
)

StageName = Literal[
    "ingest",
    "classify",
    "extract",
    "theme",
    "anonymize",
    "compare",
    "draft",
    "human_gate",
    "superdocs",
]


class DigestState(TypedDict, total=False):
    """State carried through the graph.

    Only `run_id` is truly required — every other field is populated by the node that
    owns it. Anything large is a count or an id, never the payload itself.
    """

    # Identity and inputs
    run_id: str
    input_path: str
    last_digest_path: str | None
    quarter_label: str
    prior_quarter_label: str

    # ingest
    conversations_ingested: int
    ingest_warnings: list[str]

    # classify
    conversations_relevant: int
    conversations_skipped: int
    injection_attempts: int

    # extract
    facts_extracted: int
    conversations_embedded: int

    # theme
    theme_count: int
    theme_ids: list[str]

    # anonymize
    quotes_anonymized: int
    quotes_needing_review: int

    # compare
    prior_themes_found: int
    comparison_available: bool
    comparison_note: str
    # Prior-quarter themes with no match this quarter. Declared here (rather than being
    # smuggled onto the dict untyped) because draft_node reads it to render the
    # "no longer present" lines in the What Changed section.
    disappeared_themes: list[dict[str, Any]]

    # draft
    draft_sections: dict[str, str]
    draft_warnings: list[str]

    # human_gate
    # Whether item creation has been attempted. Distinguishes "the gate has not been
    # opened yet" from "the gate was opened and there was nothing to put in it" — two
    # states that both show zero items and must not be treated the same, or re-entry
    # loops forever creating nothing.
    gate_opened: bool
    approval_items_created: int
    approval_items_approved: int
    approval_items_rejected: int
    gate_resolved: bool

    # superdocs
    superdocs_session_id: str | None
    superdocs_document_id: str | None
    superdocs_edits_sent: int
    superdocs_changes_approved: int
    superdocs_changes_rejected: int
    export_path: str | None

    # Degradation tracking. Populated when a stage ran without its normal service, so
    # the digest can disclose exactly which parts were produced by a weaker method.
    degraded_stages: list[str]
    degraded_caveats: list[str]
    rendered_locally: bool

    # Control
    error: str | None
    failed_stage: str | None
    paused_reason: str | None


def build_initial_state(
    run_id: uuid.UUID | str,
    input_path: str,
    last_digest_path: str | None = None,
    *,
    quarter_label: str = "Q3 2026",
    prior_quarter_label: str = "Q2 2026",
) -> DigestState:
    return DigestState(
        run_id=str(run_id),
        input_path=input_path,
        last_digest_path=last_digest_path,
        quarter_label=quarter_label,
        prior_quarter_label=prior_quarter_label,
        conversations_ingested=0,
        ingest_warnings=[],
        conversations_relevant=0,
        conversations_skipped=0,
        injection_attempts=0,
        facts_extracted=0,
        conversations_embedded=0,
        theme_count=0,
        theme_ids=[],
        quotes_anonymized=0,
        quotes_needing_review=0,
        prior_themes_found=0,
        comparison_available=False,
        comparison_note="",
        disappeared_themes=[],
        draft_sections={},
        draft_warnings=[],
        gate_opened=False,
        approval_items_created=0,
        approval_items_approved=0,
        approval_items_rejected=0,
        gate_resolved=False,
        superdocs_session_id=None,
        superdocs_document_id=None,
        superdocs_edits_sent=0,
        superdocs_changes_approved=0,
        superdocs_changes_rejected=0,
        export_path=None,
        degraded_stages=[],
        degraded_caveats=[],
        rendered_locally=False,
        error=None,
        failed_stage=None,
        paused_reason=None,
    )


def state_summary(state: DigestState) -> dict[str, Any]:
    """Compact view for API responses and the run timeline."""
    return {
        "run_id": state.get("run_id"),
        "conversations": {
            "ingested": state.get("conversations_ingested", 0),
            "relevant": state.get("conversations_relevant", 0),
            "skipped": state.get("conversations_skipped", 0),
        },
        "themes": state.get("theme_count", 0),
        "quotes": {
            "anonymized": state.get("quotes_anonymized", 0),
            "needing_review": state.get("quotes_needing_review", 0),
        },
        "comparison_available": state.get("comparison_available", False),
        "injection_attempts": state.get("injection_attempts", 0),
        "degraded_stages": state.get("degraded_stages", []),
        "rendered_locally": state.get("rendered_locally", False),
        "export_path": state.get("export_path"),
        "error": state.get("error"),
    }
