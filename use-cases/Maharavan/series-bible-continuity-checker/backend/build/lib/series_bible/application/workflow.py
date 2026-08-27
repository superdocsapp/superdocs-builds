from __future__ import annotations
from typing import Any, TypedDict
from langgraph.graph import END, START, StateGraph

class WorkflowState(TypedDict, total=False):
    run_id: str
    series_id: str
    document_ids: list[str]
    facts: list[dict[str, Any]]
    findings: list[dict[str, Any]]
    completed_stages: list[str]
    requires_review: bool
    resolution: str
    proposed_change_id: str
    approved: bool
    exported: bool

STAGES = ("INGEST", "EXTRACT_FACTS", "VALIDATE_FACTS", "BUILD_OR_UPDATE_BIBLE", "RETRIEVE_RELEVANT_FACTS", "CHECK_CONTINUITY", "CLASSIFY_FINDINGS", "PERSIST_FINDINGS")

def complete(stage: str):
    async def node(state: WorkflowState) -> WorkflowState:
        completed = list(dict.fromkeys([*state.get("completed_stages", []), stage]))
        return {"completed_stages": completed}
    return node

def after_findings(state: WorkflowState) -> str:
    return "HUMAN_REVIEW" if state.get("findings") else "UPDATE_BIBLE"

def after_review(state: WorkflowState) -> str:
    if state.get("resolution") == "KEEP_EXISTING" and state.get("proposed_change_id"):
        return "CREATE_PROPOSED_CHANGE"
    return "UPDATE_BIBLE"

def after_approval(state: WorkflowState) -> str:
    return "SUPERDOCS_APPROVE" if state.get("approved") else "UPDATE_BIBLE"

def build_workflow():
    """Visible decision graph; persisted run records provide idempotent restart checkpoints."""
    graph = StateGraph(WorkflowState)
    for stage in STAGES:
        graph.add_node(stage, complete(stage))
    for stage in ("HUMAN_REVIEW", "CREATE_PROPOSED_CHANGE", "SUPERDOCS_EDIT", "HUMAN_APPROVAL", "SUPERDOCS_APPROVE", "UPDATE_BIBLE", "EXPORT"):
        graph.add_node(stage, complete(stage))
    graph.add_edge(START, "INGEST")
    for left, right in zip(STAGES, STAGES[1:]):
        graph.add_edge(left, right)
    graph.add_conditional_edges("PERSIST_FINDINGS", after_findings, {"HUMAN_REVIEW": "HUMAN_REVIEW", "UPDATE_BIBLE": "UPDATE_BIBLE"})
    graph.add_conditional_edges("HUMAN_REVIEW", after_review, {"CREATE_PROPOSED_CHANGE": "CREATE_PROPOSED_CHANGE", "UPDATE_BIBLE": "UPDATE_BIBLE"})
    graph.add_edge("CREATE_PROPOSED_CHANGE", "SUPERDOCS_EDIT")
    graph.add_edge("SUPERDOCS_EDIT", "HUMAN_APPROVAL")
    graph.add_conditional_edges("HUMAN_APPROVAL", after_approval, {"SUPERDOCS_APPROVE": "SUPERDOCS_APPROVE", "UPDATE_BIBLE": "UPDATE_BIBLE"})
    graph.add_edge("SUPERDOCS_APPROVE", "UPDATE_BIBLE")
    graph.add_edge("UPDATE_BIBLE", "EXPORT")
    graph.add_edge("EXPORT", END)
    return graph.compile()

workflow = build_workflow()
