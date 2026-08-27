"""The inbound review as a durable, human-gated LangGraph.

Three nodes — propose, gate, apply — with a checkpointer so the run survives a crash or a
days-long pause, and a real ``interrupt`` at the gate so the human approves changes item by item.
The graph holds only ids and small serialisable data; the review round itself lives in the Store,
which is the source of truth. Nodes close over the service clients, so the same graph runs against
the fakes (keyless tests) and the live services.

Path-changing decisions live in ``_route_after_propose``: nothing to review, or a parked run
(budget/quota), skips the gate — the graph adapts instead of marching through empty stages.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from typing import Any, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from notion_review.config import Config
from notion_review.docx_markup import parse_docx
from notion_review.domain import ProposedChange, ReviewRound, RoundStatus, Submission
from notion_review.logging import get_logger
from notion_review.notion.base import NotionClient
from notion_review.roundtrip.inbound import (
    MatchedEdit,
    apply_decisions,
    match_edits,
    post_page_summaries,
    propose_changes,
)
from notion_review.store import Store
from notion_review.superdocs.base import SuperDocsClient

_log = get_logger("notion_review.graph")


class ReviewState(TypedDict, total=False):
    round_id: str
    matched: list[dict[str, Any]]
    decisions: list[dict[str, Any]]
    cursor: int  # how many matched edits have been proposed so far (the batch loop's position)


@dataclass
class ReviewGate:
    """The paused state handed to the human: the round and the changes awaiting approval."""

    round: ReviewRound
    pending: list[ProposedChange]


def submission_key(docx_bytes: bytes) -> str:
    """Identify a returned copy by its content, so a re-delivery is free and a second reviewer
    is not mistaken for one."""
    return hashlib.sha256(docx_bytes).hexdigest()[:16]


def _load(store: Store, round_id: str) -> ReviewRound:
    round_ = store.get(round_id)
    if round_ is None:
        raise KeyError(f"review round not found: {round_id}")
    return round_


def build_review_graph(
    *,
    notion: NotionClient,
    superdocs: SuperDocsClient,
    store: Store,
    config: Config,
    checkpointer: Any,
) -> Any:
    """Compile the propose → gate → apply graph with its dependencies bound in."""

    def propose(state: ReviewState) -> ReviewState:
        """Propose the next batch of edits — one SuperDocs request, one operation.

        A SuperDocs session holds one pending proposal set at a time, so a review larger than
        ``sections_per_op`` cannot be proposed in one go: the next batch goes out only after this
        one has been gated and applied (which resolves the pending set and frees the session).
        """
        round_ = _load(store, state["round_id"])
        round_.status = RoundStatus.INGESTING
        edits = [MatchedEdit.model_validate(m) for m in state.get("matched", [])]
        cursor = state.get("cursor", 0)
        batch = edits[cursor : cursor + config.sections_per_op]
        started = time.perf_counter()
        propose_changes(round_, superdocs, batch, config)
        elapsed = (time.perf_counter() - started) * 1000
        round_.stage_timings_ms["propose"] = round_.stage_timings_ms.get("propose", 0.0) + elapsed
        if round_.status != RoundStatus.PARKED and round_.pending():
            round_.status = RoundStatus.AWAITING_APPROVAL
        store.save(round_)
        _log.info(
            "changes_proposed",
            extra={
                "round_id": round_.id,
                "batch": f"{cursor + len(batch)}/{len(edits)}",
                "pending": len(round_.pending()),
                "ops": round_.ops_spent,
            },
        )
        return {"cursor": cursor + len(batch)}

    def gate(state: ReviewState) -> ReviewState:
        round_ = _load(store, state["round_id"])
        payload = {
            "round_id": round_.id,
            "pending": [p.model_dump(mode="json") for p in round_.pending()],
        }
        decisions = interrupt(payload)  # pause here until a human resumes with decisions
        return {"decisions": list(decisions)}

    def apply(state: ReviewState) -> ReviewState:
        round_ = _load(store, state["round_id"])
        started = time.perf_counter()
        apply_decisions(round_, state.get("decisions", []), notion, superdocs, config)
        elapsed = (time.perf_counter() - started) * 1000
        round_.stage_timings_ms["apply"] = round_.stage_timings_ms.get("apply", 0.0) + elapsed
        store.save(round_)
        _log.info(
            "changes_applied",
            extra={"round_id": round_.id, "status": round_.status.value},
        )
        return {}

    def finalize(state: ReviewState) -> ReviewState:
        round_ = _load(store, state["round_id"])
        if round_.pending():
            # An undecided change is still outstanding — the round is not over, so do not close
            # it or announce a completion the page owner has not actually reached.
            round_.status = RoundStatus.AWAITING_APPROVAL
            store.save(round_)
            return {}
        if round_.status not in (RoundStatus.PARKED, RoundStatus.FAILED):
            round_.status = RoundStatus.COMPLETED
        # One accurate summary per page, now that every batch has been decided.
        post_page_summaries(round_, notion)
        store.save(round_)
        return {}

    def _more_batches(state: ReviewState) -> bool:
        return state.get("cursor", 0) < len(state.get("matched", []))

    def route_after_propose(state: ReviewState) -> str:
        round_ = _load(store, state["round_id"])
        if round_.status == RoundStatus.PARKED:
            return "finalize"
        if round_.pending():
            return "gate"
        # This batch proposed nothing; move on to the next rather than ending the round.
        return "propose" if _more_batches(state) else "finalize"

    def route_after_apply(state: ReviewState) -> str:
        """Continue with the next batch once the applied one has freed SuperDocs' session."""
        round_ = _load(store, state["round_id"])
        if round_.status == RoundStatus.PARKED or round_.ops_spent >= config.max_ops_per_round:
            return "finalize"
        if round_.pending():
            return "gate"  # changes from this batch are still undecided; wait for them
        return "propose" if _more_batches(state) else "finalize"

    graph = StateGraph(ReviewState)
    graph.add_node("propose", propose)
    graph.add_node("gate", gate)
    graph.add_node("apply", apply)
    graph.add_node("finalize", finalize)
    graph.add_edge(START, "propose")
    graph.add_conditional_edges(
        "propose",
        route_after_propose,
        {"gate": "gate", "propose": "propose", "finalize": "finalize"},
    )
    graph.add_edge("gate", "apply")
    graph.add_conditional_edges(
        "apply",
        route_after_apply,
        {"gate": "gate", "propose": "propose", "finalize": "finalize"},
    )
    graph.add_edge("finalize", END)
    return graph.compile(checkpointer=checkpointer)


class InboundController:
    """Drives the inbound graph: start a review to the gate, then submit the human's decisions."""

    def __init__(
        self,
        *,
        notion: NotionClient,
        superdocs: SuperDocsClient,
        store: Store,
        config: Config,
        checkpointer: Any | None = None,
    ) -> None:
        self._store = store
        self._graph = build_review_graph(
            notion=notion,
            superdocs=superdocs,
            store=store,
            config=config,
            checkpointer=checkpointer if checkpointer is not None else InMemorySaver(),
        )

    def start(self, *, round_id: str, docx_bytes: bytes, filename: str = "") -> ReviewGate:
        """Take in one returned copy: parse it, propose its changes, pause at the approval gate.

        A round goes out to several reviewers, so it takes in several returned copies — each one
        its own submission, identified by a content hash of the file and proposed on its own graph
        thread, merging into the round's single set of proposals and its single Notion queue.

        Idempotent on the file, not on the round: the *same* file arriving twice (a restart, a
        channel that re-delivers) is recognised and costs nothing, while a *different* file for
        the same round is another reviewer whose changes must not be lost.
        """
        key = submission_key(docx_bytes)
        round_ = _load(self._store, round_id)
        if round_.has_submission(key):
            return ReviewGate(round=round_, pending=round_.pending())
        markup = parse_docx(docx_bytes)
        matched, unmatched = match_edits(markup, round_.block_map)
        if unmatched:
            _log.warning("unmatched_changes", extra={"round_id": round_id, "count": len(unmatched)})
        state: ReviewState = {
            "round_id": round_id,
            "matched": [edit.model_dump() for edit in matched],
        }
        self._graph.invoke(state, self._config(round_id, key))
        # Recorded only once the graph has run, so a crash mid-propose re-parses on restart rather
        # than marking a review taken in that was never proposed.
        round_ = _load(self._store, round_id)
        round_.submissions.append(
            Submission(
                key=key,
                filename=filename,
                reviewers=sorted({edit.reviewer for edit in matched}),
                matched=len(matched),
                unmatched=len(unmatched),
            )
        )
        round_.touch()
        self._store.save(round_)
        _log.info(
            "submission_taken_in",
            extra={
                "round_id": round_id,
                "submission": key,
                "matched": len(matched),
                "submissions": len(round_.submissions),
            },
        )
        return ReviewGate(round=round_, pending=round_.pending())

    def submit(self, *, round_id: str, decisions: list[dict[str, Any]]) -> ReviewRound:
        """Resume every paused submission with the human's decisions and apply the approved ones.

        The owner decides in one place — the round's queue in Notion — but the changes they are
        deciding on may have come from several reviewers, each proposed on its own thread. Every
        thread still waiting at the gate is resumed with the same decisions; applying is keyed on
        the proposal id and is idempotent, so a change already written is never written twice.
        """
        round_ = _load(self._store, round_id)
        resumed = 0
        for submission in round_.submissions:
            config = self._config(round_id, submission.key)
            if self._graph.get_state(config).next:  # paused at the gate; anything else is done
                self._graph.invoke(Command(resume=decisions), config)
                resumed += 1
        if not resumed and round_.pending():
            # The round is durable but its graph checkpoint is not reachable (an in-memory
            # checkpointer across a restart). Say so loudly: the decisions are still recorded in
            # Notion and nothing is lost, but they cannot be applied until the run is re-entered.
            _log.warning(
                "no_resumable_submission",
                extra={"round_id": round_id, "pending": len(round_.pending())},
            )
        return _load(self._store, round_id)

    def _config(self, round_id: str, submission_key: str) -> dict[str, Any]:
        """One graph thread per returned copy, so each reviewer's run resumes independently."""
        return {"configurable": {"thread_id": f"{round_id}:{submission_key}"}}
