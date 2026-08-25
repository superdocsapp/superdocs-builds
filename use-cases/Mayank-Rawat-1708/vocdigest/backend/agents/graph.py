"""
@file: backend/agents/graph.py
@description: Assembles the nine nodes into a LangGraph StateGraph and provides the two
    entry points the API uses: start_run (fresh) and resume_run (after a pause, a crash,
    or an approval decision). Because every node checkpoints and skips itself when
    already complete, both entry points run the same graph — resume is not a separate
    code path, which is what keeps the two from drifting apart.
@flow: build_graph() wires ingest -> classify -> extract -> theme -> anonymize ->
    compare -> draft -> human_gate -> superdocs -> END. execute_run() loads or creates
    the run row, rehydrates state from the checkpoint, invokes the graph, and translates
    a NodePause into a normal return rather than an exception.
@dependencies:
    - langgraph.graph.StateGraph: orchestration
    - backend.agents.nodes.*: the nine stage implementations
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from langgraph.graph import END, StateGraph

from backend.agents.nodes.anonymize import AnonymizeNode
from backend.agents.nodes.base import NodeCancelled, NodePause
from backend.agents.nodes.classify import ClassifyNode
from backend.agents.nodes.compare import CompareNode
from backend.agents.nodes.draft import DraftNode
from backend.agents.nodes.extract import ExtractNode
from backend.agents.nodes.human_gate import HumanGateNode
from backend.agents.nodes.ingest import IngestNode
from backend.agents.nodes.superdocs import SuperDocsNode
from backend.agents.nodes.theme import ThemeNode
from backend.agents.state import DigestState, build_initial_state
from backend.db.database import session_scope
from backend.models import Run, RunStatus

logger = logging.getLogger(__name__)

# Node order is the pipeline order. Kept as data so the frontend timeline and the graph
# cannot disagree about what the stages are.
NODE_SEQUENCE: list[tuple[str, type]] = [
    ("ingest", IngestNode),
    ("classify", ClassifyNode),
    ("extract", ExtractNode),
    ("theme", ThemeNode),
    ("anonymize", AnonymizeNode),
    ("compare", CompareNode),
    ("draft", DraftNode),
    ("human_gate", HumanGateNode),
    ("superdocs", SuperDocsNode),
]


def build_graph():
    """Construct the compiled digest graph.

    A linear chain: branching is handled inside nodes (skip, pause, retry) rather than
    with conditional edges, because every branch here is "this stage decided something
    about itself" rather than "route to a different stage".
    """
    graph = StateGraph(DigestState)

    instances = {name: cls() for name, cls in NODE_SEQUENCE}
    for name, node in instances.items():
        graph.add_node(name, node)

    graph.set_entry_point(NODE_SEQUENCE[0][0])
    for (current, _), (nxt, _) in zip(NODE_SEQUENCE, NODE_SEQUENCE[1:]):
        graph.add_edge(current, nxt)
    graph.add_edge(NODE_SEQUENCE[-1][0], END)

    return graph.compile()


_compiled_graph = None


def get_graph():
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_graph()
    return _compiled_graph


async def create_run(
    input_path: str,
    last_digest_path: str | None = None,
    *,
    quarter_label: str = "Q3 2026",
    prior_quarter_label: str = "Q2 2026",
) -> uuid.UUID:
    """Insert a new run row and return its id. Does not start execution."""
    async with session_scope() as session:
        # Insert first so the row's id exists, then build state once against it.
        # Building state against a throwaway uuid and overwriting it left a window where
        # checkpoint_data referenced a run id that did not exist.
        run = Run(
            input_path=input_path,
            last_digest_path=last_digest_path,
            quarter_label=quarter_label,
            status=RunStatus.PENDING,
            checkpoint_data={},
        )
        session.add(run)
        await session.flush()

        state = build_initial_state(
            run.id,
            input_path,
            last_digest_path,
            quarter_label=quarter_label,
            prior_quarter_label=prior_quarter_label,
        )
        run.checkpoint_data = {"state": dict(state), "stages": {}}
        await session.flush()
        return run.id


async def load_state(run_id: uuid.UUID) -> DigestState:
    """Rebuild graph state from the checkpoint.

    On resume this is what lets the pipeline pick up mid-flight: the state carries the
    counts and ids produced by every completed stage, and each node's own checkpoint
    tells it to skip.
    """
    async with session_scope() as session:
        run = await session.get(Run, run_id)
        if run is None:
            raise LookupError(f"Run {run_id} not found")

        checkpoint = run.checkpoint_data or {}
        state: DigestState = dict(checkpoint.get("state") or {})  # type: ignore[assignment]
        if not state:
            state = build_initial_state(
                run.id, run.input_path, run.last_digest_path,
                quarter_label=run.quarter_label,
            )

        # Replay each completed stage's delta so state reflects everything already done.
        for stage_name, _ in NODE_SEQUENCE:
            stage = (checkpoint.get("stages") or {}).get(stage_name)
            if stage and stage.get("status") in {"COMPLETE", "SKIPPED"}:
                state.update((stage.get("result") or {}).get("state_delta", {}))

        state["run_id"] = str(run.id)
        state["input_path"] = run.input_path
        state["last_digest_path"] = run.last_digest_path
        state["quarter_label"] = run.quarter_label
        return state


async def persist_state(run_id: uuid.UUID, state: DigestState) -> None:
    async with session_scope() as session:
        run = await session.get(Run, run_id)
        if run is None:
            return
        checkpoint = dict(run.checkpoint_data or {})
        checkpoint["state"] = dict(state)
        run.checkpoint_data = checkpoint


#: One lock per run. claim_stage() short-circuits a stage that is COMPLETE or SKIPPED,
#: but a stage that is RUNNING is still claimable — so two executions of the same run
#: interleave through it. That is not theoretical: several endpoints schedule an
#: execution (resume, approve-all, stage retry, stage skip), and pressing two of them
#: produced two executions walking the same pipeline, which is where the approval gate's
#: repeated "GATE_OPENED / PAUSED ×6" came from, and how theme's inserts accumulated
#: 16 -> 32 -> 48 -> 80 themes for one 19-conversation run. Serialising per run at the
#: entry point is the narrow fix.
#:
#: In-process only. One uvicorn process is what this deployment runs; several would need
#: the claim itself to reject a RUNNING stage in the database.
_RUN_LOCKS: dict[str, asyncio.Lock] = {}


def _run_lock(run_id: uuid.UUID) -> asyncio.Lock:
    return _RUN_LOCKS.setdefault(str(run_id), asyncio.Lock())


async def execute_run(run_id: uuid.UUID) -> dict[str, Any]:
    """Run (or resume) the graph to its next stopping point.

    Returns a status dict rather than raising on a pause, because a pause is the normal
    outcome when a human gate is involved — the caller decides what to do next.

    A run already executing is reported as such rather than executed a second time.
    Two executions of one run do not go faster; they duplicate provider spend and
    corrupt each other's state.
    """
    lock = _run_lock(run_id)
    # No await between the check and the acquire, so within one event loop this is
    # indivisible: a second caller cannot slip past while the first is acquiring.
    if lock.locked():
        async with session_scope() as session:
            run = await session.get(Run, run_id)
            status = run.status.value if run else "UNKNOWN"
        logger.info("Run %s is already executing; ignoring the duplicate start", run_id)
        return {
            "run_id": str(run_id),
            "status": status,
            "paused": False,
            "already_running": True,
            "reason": (
                "This run is already executing. Starting it again would duplicate "
                "provider spend and let two executions overwrite each other's state."
            ),
        }
    async with lock:
        try:
            return await _execute_run_locked(run_id)
        finally:
            if not lock.locked():
                _RUN_LOCKS.pop(str(run_id), None)


async def _execute_run_locked(run_id: uuid.UUID) -> dict[str, Any]:
    """execute_run's body, with the per-run lock already held."""
    # Fresh breaker per execution: a quota that was spent an hour ago may have reset,
    # and a resumed run deserves a real attempt rather than inheriting a stale verdict.
    from backend.services.llm_gate import reset_breaker

    reset_breaker()

    state = await load_state(run_id)
    graph = get_graph()

    try:
        final_state = await graph.ainvoke(state)
        await persist_state(run_id, final_state)  # type: ignore[arg-type]
        async with session_scope() as session:
            run = await session.get(Run, run_id)
            status = run.status.value if run else "UNKNOWN"
        return {
            "run_id": str(run_id),
            "status": status,
            "paused": False,
            "state": dict(final_state),
        }

    except NodeCancelled as cancelled:
        await persist_state(run_id, state)
        logger.info("Run %s cancelled: %s", run_id, cancelled.reason)
        return {
            "run_id": str(run_id),
            "status": RunStatus.CANCELLED.value,
            "paused": False,
            "cancelled": True,
            "reason": cancelled.reason,
            "state": dict(state),
        }

    except NodePause as pause:
        await persist_state(run_id, state)
        async with session_scope() as session:
            run = await session.get(Run, run_id)
            status = run.status.value if run else RunStatus.PAUSED.value
        logger.info("Run %s paused: %s", run_id, pause.reason)
        return {
            "run_id": str(run_id),
            "status": status,
            "paused": True,
            "reason": pause.reason,
            "state": dict(state),
        }

    except Exception as exc:  # noqa: BLE001 - top-level boundary
        await persist_state(run_id, state)
        logger.exception("Run %s failed", run_id)
        return {
            "run_id": str(run_id),
            "status": RunStatus.FAILED.value,
            "paused": False,
            "error": str(exc),
            "state": dict(state),
        }