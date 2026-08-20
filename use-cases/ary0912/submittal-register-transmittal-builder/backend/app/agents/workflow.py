import time
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.agents.state import SubmittalState
from app.services.comparison import (
    compare_fire_doors,
    compare_flooring,
    compare_generic_attributes,
)

MAX_RETRIES = 2


# ============================================================
# INGEST DOCUMENTS
# ============================================================

def ingest_documents(state: SubmittalState):
    start = time.perf_counter()
    durations = dict(state.get("stage_durations") or {})
    ops = state.get("operations_count", 0) + 1

    durations["ingest"] = round((time.perf_counter() - start) * 1000, 2)

    return {
        "current_stage": "INGESTED",
        "stage_durations": durations,
        "operations_count": ops,
    }


# ============================================================
# EXTRACT REQUIREMENTS
# ============================================================

def extract_requirements(state: SubmittalState):
    start = time.perf_counter()
    durations = dict(state.get("stage_durations") or {})
    ops = state.get("operations_count", 0) + 1

    spec = state.get("specification")
    sub = state.get("submission")
    section = state.get("specification_section", "")
    scenario = state.get("scenario", "")

    if not spec or not sub:
        if section == "08 11 13" or scenario == "fire_doors":
            spec = {
                "fire_rating": "90 Minutes (1.5 Hours)",
                "steel_gauge": "16 Gauge (0.053 in / 1.3 mm)",
                "stc_rating": 38,
            }
            sub = {
                "fire_rating": "60 Minutes (1.0 Hour)",
                "steel_gauge": "16 Gauge (1.3 mm) Cold-Rolled Steel",
                "stc_rating": None,
            }
        else:
            spec = {
                "minimum_thickness": 3.0,
                "fire_performance": "Class A",
                "warranty_years": 10,
            }
            sub = {
                "thickness": 2.5,
                "fire_performance": "Class A",
                "warranty_years": 10,
            }

    durations["extract"] = round((time.perf_counter() - start) * 1000, 2)

    return {
        "specification": spec,
        "submission": sub,
        "current_stage": "EXTRACTED",
        "stage_durations": durations,
        "operations_count": ops,
    }


# ============================================================
# COMPARE DOCUMENTS
# ============================================================

def compare_documents(state: SubmittalState):
    start = time.perf_counter()
    durations = dict(state.get("stage_durations") or {})
    ops = state.get("operations_count", 0) + 1

    spec = state.get("specification", {})
    sub = state.get("submission", {})
    section = state.get("specification_section", "")
    scenario = state.get("scenario", "")
    sub_id = state.get("submittal_id", "SUB-001")

    if section == "08 11 13" or scenario == "fire_doors" or "fire_rating" in spec:
        findings = compare_fire_doors(spec, sub)
    elif "minimum_thickness" in spec:
        findings = compare_flooring(spec, sub)
    elif "attributes" in spec:
        findings = compare_generic_attributes(section or "General", sub_id, spec["attributes"])
    else:
        findings = compare_flooring(spec, sub)

    durations["compare"] = round((time.perf_counter() - start) * 1000, 2)

    return {
        "findings": [
            finding.__dict__
            for finding in findings
        ],
        "current_stage": "COMPARED",
        "stage_durations": durations,
        "operations_count": ops,
    }


# ============================================================
# DECIDE NEXT STEP (conditional routing)
# ============================================================

def decide_after_compare(state: SubmittalState) -> str:
    """Route based on comparison results.

    - If extraction failed (no findings), retry up to MAX_RETRIES.
    - If all findings are MATCH, skip human review (no deviations).
    - If any finding is a DEVIATION, require human review.
    """
    error = state.get("error")
    retry_count = state.get("retry_count", 0)

    if error and retry_count < MAX_RETRIES:
        return "extract_requirements"

    findings = state.get("findings", [])
    if not findings:
        if retry_count < MAX_RETRIES:
            return "extract_requirements"
        return "escalate_empty"

    has_deviation = any(
        f.get("result") in ("DEVIATION", "MISSING")
        for f in findings
    )

    if not has_deviation:
        return "auto_approve"

    return "wait_for_review"


# ============================================================
# AUTO-APPROVE (skip review when all findings match)
# ============================================================

def auto_approve(state: SubmittalState):
    """All findings matched — no human review needed."""
    start = time.perf_counter()
    durations = dict(state.get("stage_durations") or {})
    ops = state.get("operations_count", 0) + 1

    findings = state.get("findings", [])
    reviewed = []
    for f in findings:
        reviewed.append({
            **f,
            "status": "APPROVED",
            "reviewer": "SYSTEM_AUTO",
            "reviewer_comment": "All findings are MATCH — auto-approved.",
            "reviewed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })

    durations["auto_approve"] = round((time.perf_counter() - start) * 1000, 2)

    return {
        "findings": reviewed,
        "review_status": "AUTO_APPROVED",
        "current_stage": "REVIEWED",
        "skipped_review": True,
        "stage_durations": durations,
        "operations_count": ops,
    }


# ============================================================
# ESCALATE (extraction failed after retries)
# ============================================================

def escalate_empty(state: SubmittalState):
    """Escalation: extraction produced no findings after retries."""
    start = time.perf_counter()
    durations = dict(state.get("stage_durations") or {})
    ops = state.get("operations_count", 0) + 1

    durations["escalate"] = round((time.perf_counter() - start) * 1000, 2)

    return {
        "current_stage": "ESCALATED",
        "escalated": True,
        "error": state.get("error", "Extraction produced no findings after retries."),
        "stage_durations": durations,
        "operations_count": ops,
    }


# ============================================================
# HUMAN REVIEW GATE
# ============================================================

def wait_for_review(state: SubmittalState):
    review_request = {
        "type": "SUBMITTAL_REVIEW",
        "message": (
            "Human review is required before "
            "this submittal can continue."
        ),
        "project_id": state.get("project_id"),
        "submittal_id": state.get("submittal_id"),
        "findings": state.get("findings", []),
        "allowed_decisions": [
            "APPROVE",
            "REJECT",
            "REQUEST_CLARIFICATION",
        ],
    }

    human_review = interrupt(review_request)

    return {
        "human_review": human_review,
        "review_status": "REVIEW_COMPLETED",
        "current_stage": "REVIEWED",
    }


# ============================================================
# BUILD GRAPH
# ============================================================

def build_graph(checkpointer):
    graph = StateGraph[Any](SubmittalState)

    graph.add_node("ingest_documents", ingest_documents)
    graph.add_node("extract_requirements", extract_requirements)
    graph.add_node("compare_documents", compare_documents)
    graph.add_node("wait_for_review", wait_for_review)
    graph.add_node("auto_approve", auto_approve)
    graph.add_node("escalate_empty", escalate_empty)

    graph.add_edge(START, "ingest_documents")
    graph.add_edge("ingest_documents", "extract_requirements")
    graph.add_edge("extract_requirements", "compare_documents")

    graph.add_conditional_edges(
        "compare_documents",
        decide_after_compare,
        {
            "extract_requirements": "extract_requirements",
            "wait_for_review": "wait_for_review",
            "auto_approve": "auto_approve",
            "escalate_empty": "escalate_empty",
        },
    )

    graph.add_edge("auto_approve", END)
    graph.add_edge("escalate_empty", END)
    graph.add_edge("wait_for_review", END)

    return graph.compile(checkpointer=checkpointer)
