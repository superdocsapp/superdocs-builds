"""Executable LangGraph orchestration for ingestion-to-review analysis."""
from __future__ import annotations

from itertools import pairwise
from typing import Any, Awaitable, Callable, TypedDict

from langgraph.graph import END, START, StateGraph


class AnalysisState(TypedDict, total=False):
    run_id: str
    series_id: str
    documents: list[Any]
    facts: list[Any]
    candidates: list[Any]
    comparisons: list[Any]
    intra_comparisons: list[Any]
    findings: list[str]
    completed_stages: list[str]


Node = Callable[[AnalysisState], Awaitable[dict[str, Any]]]


def build_analysis_graph(nodes: dict[str, Node]):
    graph = StateGraph(AnalysisState)
    stages = (
        "INGEST",
        "EXTRACT_FACTS",
        "VALIDATE_FACTS",
        "BUILD_OR_UPDATE_BIBLE",
        "RETRIEVE_RELEVANT_FACTS",
        "CHECK_CONTINUITY",
        "CLASSIFY_FINDINGS",
        "PERSIST_FINDINGS",
    )
    for stage in stages:
        graph.add_node(stage, nodes[stage])
    graph.add_edge(START, stages[0])
    for left, right in pairwise(stages):
        graph.add_edge(left, right)
    graph.add_edge(stages[-1], END)
    return graph.compile()
