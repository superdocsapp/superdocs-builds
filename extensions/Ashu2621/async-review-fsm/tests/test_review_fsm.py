from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from pydantic import JsonValue
from review_fsm.fastapi_binding import create_review_router
from review_fsm.transitions import rule_for

from review_fsm import (
    TRANSITION_RULES,
    CommandType,
    InMemoryReviewPersistence,
    ReviewEvent,
    ReviewEventType,
    ReviewReconciliationError,
    ReviewRuntime,
    ReviewSnapshot,
    ReviewState,
    ReviewTransitionError,
    SQLiteReviewPersistence,
    mermaid_state_diagram,
    reconcile_runtime,
    reduce,
)


def event(
    snapshot: ReviewSnapshot,
    event_id: str,
    event_type: ReviewEventType,
    **payload: JsonValue,
) -> ReviewEvent:
    return ReviewEvent(
        event_id=event_id,
        batch_id=snapshot.batch_id,
        expected_version=snapshot.version,
        type=event_type,
        payload=payload,
    )


def test_readme_diagram_is_generated_from_transition_table() -> None:
    readme = (Path(__file__).parents[1] / "README.md").read_text(encoding="utf-8")
    diagram = readme.split("```mermaid\n", 1)[1].split("\n```", 1)[0]
    assert diagram == mermaid_state_diagram()


def test_happy_path_with_multiple_review_rounds() -> None:
    snapshot = ReviewSnapshot(batch_id="batch-1")
    cases = [
        (ReviewEventType.SUBMIT, ReviewState.SUBMITTED),
        (ReviewEventType.PROVIDER_STARTED, ReviewState.WORKING),
        (ReviewEventType.PROPOSALS_READY, ReviewState.AWAITING_REVIEW),
        (ReviewEventType.DECISIONS_RECORDED, ReviewState.RESUMING),
        (ReviewEventType.PROPOSALS_READY, ReviewState.AWAITING_REVIEW),
        (ReviewEventType.DECISIONS_RECORDED, ReviewState.RESUMING),
        (ReviewEventType.PROVIDER_COMPLETED, ReviewState.FINISHED),
    ]

    for index, (event_type, expected_state) in enumerate(cases, start=1):
        payload = {"remaining_count": 0} if event_type is ReviewEventType.DECISIONS_RECORDED else {}
        result = reduce(snapshot, event(snapshot, f"event-{index}", event_type, **payload))
        snapshot = result.snapshot
        assert snapshot.state is expected_state

    assert snapshot.version == 8
    assert len(snapshot.processed_event_ids) == 7


def test_partial_decisions_remain_pending() -> None:
    snapshot = ReviewSnapshot(
        batch_id="batch-1",
        state=ReviewState.AWAITING_REVIEW,
        version=4,
    )

    result = reduce(
        snapshot,
        event(snapshot, "decision-1", ReviewEventType.DECISIONS_RECORDED, remaining_count=2),
    )

    assert result.snapshot.state is ReviewState.PARTIALLY_DECIDED
    assert result.commands[0].type is CommandType.SUBMIT_DECISIONS


def test_duplicate_event_is_noop() -> None:
    snapshot = ReviewSnapshot(
        batch_id="batch-1",
        state=ReviewState.WORKING,
        version=3,
        processed_event_ids=frozenset({"poll-1"}),
    )
    duplicate = ReviewEvent(
        event_id="poll-1",
        batch_id="batch-1",
        expected_version=1,
        type=ReviewEventType.POLL_TICK,
    )

    result = reduce(snapshot, duplicate)

    assert result.duplicate is True
    assert result.snapshot is snapshot
    assert result.commands == ()


def test_stale_version_fails_closed() -> None:
    snapshot = ReviewSnapshot(batch_id="batch-1", version=4)
    stale = ReviewEvent(
        event_id="submit-1",
        batch_id="batch-1",
        expected_version=3,
        type=ReviewEventType.SUBMIT,
    )

    with pytest.raises(ReviewTransitionError, match="BATCH_VERSION_CONFLICT"):
        reduce(snapshot, stale)


def test_continue_action_is_invalid_for_proposal_review() -> None:
    snapshot = ReviewSnapshot(
        batch_id="batch-1",
        state=ReviewState.AWAITING_REVIEW,
        version=4,
    )

    with pytest.raises(ReviewTransitionError, match="INVALID_TRANSITION"):
        reduce(snapshot, event(snapshot, "continue-1", ReviewEventType.CONTINUE))


def test_terminal_state_cannot_move_backward() -> None:
    snapshot = ReviewSnapshot(
        batch_id="batch-1",
        state=ReviewState.FINISHED,
        version=7,
    )

    with pytest.raises(ReviewTransitionError, match="TERMINAL_STATE"):
        reduce(snapshot, event(snapshot, "poll-late", ReviewEventType.POLL_TICK))


@pytest.mark.asyncio
async def test_runtime_persists_before_commands_and_reloads_mid_review() -> None:
    persistence = InMemoryReviewPersistence()
    committed_versions: list[int] = []
    first = ReviewRuntime(
        persistence,
        after_commit=lambda result: committed_versions.append(result.snapshot.version),
    )
    snapshot = await first.create("durable-batch")
    for index, event_type in enumerate(
        (
            ReviewEventType.SUBMIT,
            ReviewEventType.PROVIDER_STARTED,
            ReviewEventType.PROPOSALS_READY,
        ),
        1,
    ):
        result = await first.dispatch(event(snapshot, f"durable-{index}", event_type))
        snapshot = result.snapshot
    assert snapshot.state is ReviewState.AWAITING_REVIEW

    restored = ReviewRuntime(persistence)
    decision = await restored.dispatch(
        event(snapshot, "durable-decision", ReviewEventType.DECISIONS_RECORDED,
              remaining_count=0)
    )
    assert decision.snapshot.state is ReviewState.RESUMING
    assert (await persistence.load("durable-batch")) == decision.snapshot
    assert committed_versions == [2, 3, 4]
    assert len(await persistence.commands()) == 6


@pytest.mark.asyncio
async def test_runtime_concurrent_versions_fail_closed() -> None:
    persistence = InMemoryReviewPersistence()
    runtime = ReviewRuntime(persistence)
    snapshot = await runtime.create("concurrent-batch")
    one = event(snapshot, "event-one", ReviewEventType.SUBMIT)
    two = event(snapshot, "event-two", ReviewEventType.SUBMIT)
    await runtime.dispatch(one)
    with pytest.raises(ReviewTransitionError, match="BATCH_VERSION_CONFLICT"):
        await runtime.dispatch(two)


def test_state_diagram_is_generated_from_declared_transitions() -> None:
    diagram = mermaid_state_diagram()
    assert diagram.startswith("stateDiagram-v2")
    assert "PARTIALLY_DECIDED --> RESUMING: DECISIONS_RECORDED" in diagram
    assert "AWAITING_CONTINUE --> RESUMING: CONTINUE" in diagram
    assert "RECOVERY_REQUIRED" in diagram


def _payload_for(event_type: ReviewEventType, target: ReviewState) -> dict[str, JsonValue]:
    if event_type is ReviewEventType.DECISIONS_RECORDED:
        return {"remaining_count": 1 if target is ReviewState.PARTIALLY_DECIDED else 0}
    if event_type is ReviewEventType.RECONCILED:
        return {"recovered_state": target.value}
    return {}


@pytest.mark.parametrize(
    ("source", "event_type", "target"),
    [
        (source, rule.event, target)
        for rule in TRANSITION_RULES
        for source in rule.sources
        for target in (
            (source,) if rule.event is ReviewEventType.POLL_TICK else rule.targets
        )
    ],
)
def test_every_declared_transition_executes(
    source: ReviewState,
    event_type: ReviewEventType,
    target: ReviewState,
) -> None:
    snapshot = ReviewSnapshot(batch_id="exhaustive", state=source, version=7)
    result = reduce(
        snapshot,
        event(
            snapshot,
            f"{source.value}-{event_type.value}-{target.value}",
            event_type,
            **_payload_for(event_type, target),
        ),
    )
    assert result.snapshot.state is target


@pytest.mark.parametrize(
    ("source", "event_type"),
    [
        (source, event_type)
        for source in ReviewState
        if source not in {ReviewState.FINISHED, ReviewState.FAILED, ReviewState.CANCELLED,
                          ReviewState.PARTIAL_STOPPED}
        for event_type in ReviewEventType
        if rule_for(source, event_type) is None
    ],
)
def test_every_undeclared_transition_fails_closed(
    source: ReviewState,
    event_type: ReviewEventType,
) -> None:
    snapshot = ReviewSnapshot(batch_id="invalid", state=source, version=3)
    with pytest.raises(ReviewTransitionError, match="INVALID_TRANSITION"):
        reduce(snapshot, event(snapshot, f"bad-{source.value}-{event_type.value}", event_type))


@pytest.mark.asyncio
async def test_sqlite_adapter_survives_server_restart_and_partial_review(tmp_path: Path) -> None:
    database = tmp_path / "review.sqlite3"
    first = ReviewRuntime(SQLiteReviewPersistence(database))
    snapshot = await first.create("sqlite-review", context={"job_id": "job-durable"})
    for index, kind in enumerate(
        (
            ReviewEventType.SUBMIT,
            ReviewEventType.PROVIDER_STARTED,
            ReviewEventType.PROPOSALS_READY,
            ReviewEventType.DECISIONS_RECORDED,
        ),
        1,
    ):
        payload: dict[str, JsonValue] = {}
        if kind is ReviewEventType.PROVIDER_STARTED:
            payload = {"job_id": "job-durable", "session_id": "session-durable"}
        if kind is ReviewEventType.DECISIONS_RECORDED:
            payload = {"remaining_count": 1, "decided_change_ids": ["change-one"]}
        result = await first.dispatch(event(snapshot, f"sqlite-{index}", kind, **payload))
        snapshot = result.snapshot
    assert snapshot.state is ReviewState.PARTIALLY_DECIDED

    restored = ReviewRuntime(SQLiteReviewPersistence(database))
    loaded = await restored.load("sqlite-review")
    assert loaded == snapshot
    commands = await SQLiteReviewPersistence(database).commands("sqlite-review")
    assert len({command.idempotency_key for command in commands}) == len(commands)


class _FakeProvider:
    def __init__(self, status: str, *, kind: str = "review") -> None:
        self.status = status
        self.kind = kind
        self.calls: list[str] = []

    async def get_job(self, job_id: str) -> dict[str, JsonValue]:
        self.calls.append(job_id)
        return {
            "job_id": job_id,
            "status": self.status,
            "metadata": {"kind": self.kind},
            "pending_changes": [{"change_id": "change-two"}],
        }


@pytest.mark.asyncio
async def test_reconciliation_fetches_durable_provider_state() -> None:
    persistence = InMemoryReviewPersistence()
    runtime = ReviewRuntime(persistence)
    snapshot = await runtime.create(
        "reconcile-batch",
        context={"job_id": "job-1", "decided_change_ids": ["change-one"]},
    )
    snapshot = (
        await runtime.dispatch(event(snapshot, "submit", ReviewEventType.SUBMIT))
    ).snapshot
    provider = _FakeProvider("awaiting_approval")
    restored = await reconcile_runtime(runtime, batch_id=snapshot.batch_id, provider=provider)
    assert restored.state is ReviewState.PARTIALLY_DECIDED
    assert provider.calls == ["job-1"]


@pytest.mark.asyncio
async def test_expired_provider_job_stays_in_explicit_recovery_state() -> None:
    runtime = ReviewRuntime(InMemoryReviewPersistence())
    snapshot = await runtime.create("expired", context={"job_id": "job-expired"})
    snapshot = (
        await runtime.dispatch(event(snapshot, "submit-expired", ReviewEventType.SUBMIT))
    ).snapshot
    with pytest.raises(ReviewReconciliationError, match="PROVIDER_JOB_EXPIRED"):
        await reconcile_runtime(
            runtime,
            batch_id=snapshot.batch_id,
            provider=_FakeProvider("expired"),
        )
    current = await runtime.load(snapshot.batch_id)
    assert current is not None and current.state is ReviewState.RECOVERY_REQUIRED


@pytest.mark.asyncio
async def test_fastapi_binding_creates_dispatches_and_restores() -> None:
    persistence = InMemoryReviewPersistence()
    provider = _FakeProvider("in_progress")
    app = FastAPI()
    app.include_router(
        create_review_router(lambda: ReviewRuntime(persistence), lambda: provider)
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        created = await client.post(
            "/review-fsm/batches",
            json={"batch_id": "bound", "context": {"job_id": "job-bound"}},
        )
        assert created.status_code == 201
        dispatched = await client.post(
            "/review-fsm/batches/bound/events",
            json={"event_id": "bound-submit", "expected_version": 1, "type": "SUBMIT"},
        )
        assert dispatched.json()["state"] == "SUBMITTED"
        reconciled = await client.post("/review-fsm/batches/bound/reconcile")
        assert reconciled.status_code == 200
        assert reconciled.json()["state"] == "WORKING"
