"""Agents package — LangGraph orchestration."""

__all__ = [
    "NODE_ORDER",
    "build_brief_graph",
    "build_validated_brief_graph",
    "run_brief_pipeline",
]


def __getattr__(name: str):
    if name in {"NODE_ORDER", "build_brief_graph", "build_validated_brief_graph"}:
        from app.agents import graph as _graph

        return getattr(_graph, name)
    if name == "run_brief_pipeline":
        from app.agents.runner import run_brief_pipeline

        return run_brief_pipeline
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
