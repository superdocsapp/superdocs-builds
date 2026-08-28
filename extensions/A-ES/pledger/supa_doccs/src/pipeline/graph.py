"""Pipeline graph assembly — registers all nodes and conditional edges.

Builds the LangGraph StateGraph with all 13 pipeline nodes and conditional
routing edges. Handles graceful degradation when langgraph is not installed.

Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 2.2
"""

from __future__ import annotations

from collections.abc import Callable

from src.pipeline.config import load_config
from src.pipeline.routing import make_routing_fn
from src.pipeline.state import PipelineConfig, PipelineState

# Node imports
from src.pipeline.nodes.ingest import ingest
from src.pipeline.nodes.extract_text import extract_text
from src.pipeline.nodes.classify_document import classify_document
from src.pipeline.nodes.chunk import chunk
from src.pipeline.nodes.embed import embed
from src.pipeline.nodes.extract_claims import extract_claims
from src.pipeline.nodes.match_rules import match_rules
from src.pipeline.nodes.match_rules_against_sources import match_rules_against_sources
from src.pipeline.nodes.merge_findings import merge_findings
from src.pipeline.nodes.score_confidence import score_confidence
from src.pipeline.nodes.route_to_queue import route_to_queue
from src.pipeline.nodes.human_review import human_review
from src.pipeline.nodes.finalize import finalize


# Path maps for conditional edges (source_node → {decision: target_node})
PATH_MAPS: dict[str, dict[str, str]] = {
    "ingest": {"next": "extract_text", "escalate": "route_to_queue"},
    "extract_text": {
        "next": "classify_document",
        "retry": "extract_text",
        "escalate": "route_to_queue",
    },
    "classify_document": {
        "next": "chunk",
        "escalate": "route_to_queue",
        "retry": "classify_document",
    },
    "chunk": {"next": "embed", "escalate": "route_to_queue"},
    "embed": {
        "next": "extract_claims",
        "retry": "embed",
        "escalate": "route_to_queue",
    },
    "extract_claims": {
        "next": "match_rules",
        "retry": "extract_claims",
        "escalate": "route_to_queue",
    },
    "match_rules": {
        "next": "match_rules_against_sources",
        "retry": "match_rules",
        "escalate": "route_to_queue",
    },
    "match_rules_against_sources": {
        "next": "merge_findings",
        "retry": "match_rules_against_sources",
        "escalate": "route_to_queue",
    },
    "merge_findings": {
        "next": "score_confidence",
        "escalate": "route_to_queue",
    },
    "score_confidence": {
        "next": "route_to_queue",
        "retry": "score_confidence",
        "escalate": "route_to_queue",
    },
    "route_to_queue": {
        "escalate": "human_review",
        "next": "finalize",
        "retry": "route_to_queue",
    },
    "human_review": {"finalize": "finalize", "escalate": "route_to_queue"},
    "finalize": {"end": "__end__", "retry": "finalize", "escalate": "__end__"},
}

# Node function registry
NODES: dict[str, Callable] = {
    "ingest": ingest,
    "extract_text": extract_text,
    "classify_document": classify_document,
    "chunk": chunk,
    "embed": embed,
    "extract_claims": extract_claims,
    "match_rules": match_rules,
    "match_rules_against_sources": match_rules_against_sources,
    "merge_findings": merge_findings,
    "score_confidence": score_confidence,
    "route_to_queue": route_to_queue,
    "human_review": human_review,
    "finalize": finalize,
}

# Entry point for the graph
ENTRY_POINT = "ingest"

# Try importing langgraph — graceful degradation if not installed
_LANGGRAPH_AVAILABLE = False
try:
    from langgraph.graph import END, StateGraph

    _LANGGRAPH_AVAILABLE = True
except ImportError:
    pass


def build_graph(config: PipelineConfig | None = None):
    """Build the LangGraph StateGraph with all nodes and conditional edges.

    Registers all 13 pipeline nodes, wires conditional edges using the
    routing functions from routing.py, sets entry point at 'ingest', and
    terminates at END after 'finalize' completes successfully.

    Retry edge logic increments the retries dict for the failing node and
    restores the pre-node checkpoint state (only the retries key is updated).

    Args:
        config: Pipeline configuration. If None, loads defaults via load_config().

    Returns:
        The compiled LangGraph graph ready for invocation.

    Raises:
        ImportError: If the langgraph package is not installed.
    """
    if not _LANGGRAPH_AVAILABLE:
        raise ImportError(
            "The 'langgraph' package is required to build the pipeline graph. "
            "Install it with: pip install langgraph"
        )

    if config is None:
        config = load_config()

    # Create the StateGraph with PipelineState as the state schema
    graph = StateGraph(PipelineState)

    # Register all nodes
    for node_name, node_fn in NODES.items():
        graph.add_node(node_name, node_fn)

    # Set entry point
    graph.set_entry_point(ENTRY_POINT)

    # Register conditional edges for each node
    for node_name in NODES:
        path_map = PATH_MAPS[node_name]
        routing_fn = make_routing_fn(node_name, config)

        # Replace "__end__" sentinel with LangGraph's END constant
        resolved_path_map = {
            decision: END if target == "__end__" else target
            for decision, target in path_map.items()
        }

        graph.add_conditional_edges(node_name, routing_fn, resolved_path_map)

    # Compile the graph
    return graph.compile()
