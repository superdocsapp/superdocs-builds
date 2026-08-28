"""Unit tests for the human review polling service.

Tests cover:
- poll_once resumes a run when all decisions are complete
- poll_once does NOT resume when decisions are incomplete
- poll_once sends reminders for overdue items
- Multiple pending runs handled correctly
"""

import asyncio

import pytest
from datetime import datetime, timezone, timedelta

from src.pipeline.config import load_config, PipelineConfig
from src.pipeline.polling import PollingService


# --- Mock Implementations ---


class MockDecisionChecker:
    """Mock decision checker with configurable completeness per run."""

    def __init__(self, completeness: dict[str, bool] | None = None) -> None:
        self._completeness = completeness or {}
        self.checked_runs: list[str] = []

    async def check_completeness(self, run_id: str) -> bool:
        self.checked_runs.append(run_id)
        return self._completeness.get(run_id, False)


class MockGraphResumer:
    """Mock graph resumer that records which runs were resumed."""

    def __init__(self) -> None:
        self.resumed_runs: list[str] = []

    async def resume(self, run_id: str) -> None:
        self.resumed_runs.append(run_id)


class MockReminderWriter:
    """Mock reminder writer that records reminder calls."""

    def __init__(self) -> None:
        self.reminders: list[tuple[str, list[str]]] = []

    async def write_reminder(self, run_id: str, claim_ids: list[str]) -> None:
        self.reminders.append((run_id, claim_ids))


class MockPollableRunsReader:
    """Mock runs reader that returns preconfigured pending runs."""

    def __init__(self, pending_runs: list[dict] | None = None) -> None:
        self._pending_runs = pending_runs or []

    async def get_pending_runs(self) -> list[dict]:
        return self._pending_runs


class FailingDecisionChecker:
    """Decision checker that raises an exception."""

    async def check_completeness(self, run_id: str) -> bool:
        raise RuntimeError("Database connection failed")


class FailingGraphResumer:
    """Graph resumer that raises an exception."""

    async def resume(self, run_id: str) -> None:
        raise RuntimeError("Resume API unreachable")


# --- Fixtures ---


@pytest.fixture
def config() -> PipelineConfig:
    """Return a default pipeline config."""
    return load_config()


@pytest.fixture
def now() -> datetime:
    """Return a fixed 'now' time for test consistency."""
    return datetime.now(timezone.utc)


# --- Tests: Resumes when all decisions are complete ---


@pytest.mark.anyio
async def test_poll_once_resumes_run_when_all_decisions_complete(
    config: PipelineConfig, now: datetime
):
    """poll_once should resume a run when all decisions have been received."""
    decision_checker = MockDecisionChecker(completeness={"run-1": True})
    graph_resumer = MockGraphResumer()
    reminder_writer = MockReminderWriter()
    runs_reader = MockPollableRunsReader(
        pending_runs=[
            {
                "run_id": "run-1",
                "escalated_claim_ids": ["c1", "c2"],
                "interrupted_at": now - timedelta(hours=1),
                "last_reminder_at": None,
            }
        ]
    )

    service = PollingService(
        config=config,
        decision_checker=decision_checker,
        graph_resumer=graph_resumer,
        reminder_writer=reminder_writer,
        runs_reader=runs_reader,
    )

    await service.poll_once()

    # Run should have been resumed
    assert "run-1" in graph_resumer.resumed_runs
    # No reminders should have been sent (run was resumed)
    assert len(reminder_writer.reminders) == 0


# --- Tests: Does NOT resume when decisions are incomplete ---


@pytest.mark.anyio
async def test_poll_once_does_not_resume_when_decisions_incomplete(
    config: PipelineConfig, now: datetime
):
    """poll_once should NOT resume a run when decisions are still pending."""
    decision_checker = MockDecisionChecker(completeness={"run-1": False})
    graph_resumer = MockGraphResumer()
    reminder_writer = MockReminderWriter()
    runs_reader = MockPollableRunsReader(
        pending_runs=[
            {
                "run_id": "run-1",
                "escalated_claim_ids": ["c1", "c2"],
                "interrupted_at": now - timedelta(hours=1),
                "last_reminder_at": None,
            }
        ]
    )

    service = PollingService(
        config=config,
        decision_checker=decision_checker,
        graph_resumer=graph_resumer,
        reminder_writer=reminder_writer,
        runs_reader=runs_reader,
    )

    await service.poll_once()

    # Run should NOT have been resumed
    assert len(graph_resumer.resumed_runs) == 0


# --- Tests: Sends reminders for overdue items ---


@pytest.mark.anyio
async def test_poll_once_sends_reminder_for_overdue_items(
    config: PipelineConfig, now: datetime
):
    """poll_once should send reminders when reminder_interval_hours has elapsed."""
    # Default reminder_interval_hours is 24
    decision_checker = MockDecisionChecker(completeness={"run-1": False})
    graph_resumer = MockGraphResumer()
    reminder_writer = MockReminderWriter()
    # Interrupted 25 hours ago, no reminder sent yet
    runs_reader = MockPollableRunsReader(
        pending_runs=[
            {
                "run_id": "run-1",
                "escalated_claim_ids": ["c1", "c2", "c3"],
                "interrupted_at": now - timedelta(hours=25),
                "last_reminder_at": None,
            }
        ]
    )

    service = PollingService(
        config=config,
        decision_checker=decision_checker,
        graph_resumer=graph_resumer,
        reminder_writer=reminder_writer,
        runs_reader=runs_reader,
    )

    await service.poll_once()

    # Reminder should have been sent
    assert len(reminder_writer.reminders) == 1
    run_id, claim_ids = reminder_writer.reminders[0]
    assert run_id == "run-1"
    assert set(claim_ids) == {"c1", "c2", "c3"}


@pytest.mark.anyio
async def test_poll_once_no_reminder_when_interval_not_elapsed(
    config: PipelineConfig, now: datetime
):
    """poll_once should NOT send reminders if reminder interval hasn't elapsed."""
    decision_checker = MockDecisionChecker(completeness={"run-1": False})
    graph_resumer = MockGraphResumer()
    reminder_writer = MockReminderWriter()
    # Interrupted only 10 hours ago (less than 24h default)
    runs_reader = MockPollableRunsReader(
        pending_runs=[
            {
                "run_id": "run-1",
                "escalated_claim_ids": ["c1"],
                "interrupted_at": now - timedelta(hours=10),
                "last_reminder_at": None,
            }
        ]
    )

    service = PollingService(
        config=config,
        decision_checker=decision_checker,
        graph_resumer=graph_resumer,
        reminder_writer=reminder_writer,
        runs_reader=runs_reader,
    )

    await service.poll_once()

    # No reminder should have been sent
    assert len(reminder_writer.reminders) == 0


@pytest.mark.anyio
async def test_poll_once_reminder_uses_last_reminder_time(
    config: PipelineConfig, now: datetime
):
    """Reminder interval should be measured from last_reminder_at, not interrupted_at."""
    decision_checker = MockDecisionChecker(completeness={"run-1": False})
    graph_resumer = MockGraphResumer()
    reminder_writer = MockReminderWriter()
    # Interrupted 50 hours ago, but last reminder was 10 hours ago
    runs_reader = MockPollableRunsReader(
        pending_runs=[
            {
                "run_id": "run-1",
                "escalated_claim_ids": ["c1"],
                "interrupted_at": now - timedelta(hours=50),
                "last_reminder_at": now - timedelta(hours=10),
            }
        ]
    )

    service = PollingService(
        config=config,
        decision_checker=decision_checker,
        graph_resumer=graph_resumer,
        reminder_writer=reminder_writer,
        runs_reader=runs_reader,
    )

    await service.poll_once()

    # Should NOT send reminder since last_reminder_at was only 10h ago (< 24h)
    assert len(reminder_writer.reminders) == 0


@pytest.mark.anyio
async def test_poll_once_reminder_sent_when_last_reminder_overdue(
    config: PipelineConfig, now: datetime
):
    """Reminder should be sent when last_reminder_at is more than interval_hours ago."""
    decision_checker = MockDecisionChecker(completeness={"run-1": False})
    graph_resumer = MockGraphResumer()
    reminder_writer = MockReminderWriter()
    # Interrupted 50 hours ago, last reminder was 25 hours ago
    runs_reader = MockPollableRunsReader(
        pending_runs=[
            {
                "run_id": "run-1",
                "escalated_claim_ids": ["c1", "c2"],
                "interrupted_at": now - timedelta(hours=50),
                "last_reminder_at": now - timedelta(hours=25),
            }
        ]
    )

    service = PollingService(
        config=config,
        decision_checker=decision_checker,
        graph_resumer=graph_resumer,
        reminder_writer=reminder_writer,
        runs_reader=runs_reader,
    )

    await service.poll_once()

    # Should send reminder since 25h > 24h interval
    assert len(reminder_writer.reminders) == 1


# --- Tests: Multiple pending runs handled correctly ---


@pytest.mark.anyio
async def test_poll_once_handles_multiple_pending_runs(
    config: PipelineConfig, now: datetime
):
    """poll_once should correctly process multiple pending runs independently."""
    decision_checker = MockDecisionChecker(
        completeness={
            "run-1": True,   # Complete — should resume
            "run-2": False,  # Incomplete — should NOT resume
            "run-3": True,   # Complete — should resume
        }
    )
    graph_resumer = MockGraphResumer()
    reminder_writer = MockReminderWriter()
    runs_reader = MockPollableRunsReader(
        pending_runs=[
            {
                "run_id": "run-1",
                "escalated_claim_ids": ["c1"],
                "interrupted_at": now - timedelta(hours=1),
                "last_reminder_at": None,
            },
            {
                "run_id": "run-2",
                "escalated_claim_ids": ["c2", "c3"],
                "interrupted_at": now - timedelta(hours=30),
                "last_reminder_at": None,
            },
            {
                "run_id": "run-3",
                "escalated_claim_ids": ["c4"],
                "interrupted_at": now - timedelta(hours=2),
                "last_reminder_at": None,
            },
        ]
    )

    service = PollingService(
        config=config,
        decision_checker=decision_checker,
        graph_resumer=graph_resumer,
        reminder_writer=reminder_writer,
        runs_reader=runs_reader,
    )

    await service.poll_once()

    # run-1 and run-3 should be resumed
    assert set(graph_resumer.resumed_runs) == {"run-1", "run-3"}
    # run-2 should get a reminder (30h > 24h interval)
    assert len(reminder_writer.reminders) == 1
    assert reminder_writer.reminders[0][0] == "run-2"


@pytest.mark.anyio
async def test_poll_once_no_pending_runs(config: PipelineConfig):
    """poll_once should handle the case of no pending runs gracefully."""
    decision_checker = MockDecisionChecker()
    graph_resumer = MockGraphResumer()
    reminder_writer = MockReminderWriter()
    runs_reader = MockPollableRunsReader(pending_runs=[])

    service = PollingService(
        config=config,
        decision_checker=decision_checker,
        graph_resumer=graph_resumer,
        reminder_writer=reminder_writer,
        runs_reader=runs_reader,
    )

    await service.poll_once()

    assert len(graph_resumer.resumed_runs) == 0
    assert len(reminder_writer.reminders) == 0


# --- Tests: Error handling ---


@pytest.mark.anyio
async def test_poll_once_continues_on_error_for_one_run(
    config: PipelineConfig, now: datetime
):
    """If processing one run fails, other runs should still be processed."""
    # Use a failing checker for run-1, but run-2 should still work
    class SelectiveChecker:
        def __init__(self) -> None:
            self.checked: list[str] = []

        async def check_completeness(self, run_id: str) -> bool:
            self.checked.append(run_id)
            if run_id == "run-1":
                raise RuntimeError("DB error")
            return True

    checker = SelectiveChecker()
    graph_resumer = MockGraphResumer()
    reminder_writer = MockReminderWriter()
    runs_reader = MockPollableRunsReader(
        pending_runs=[
            {
                "run_id": "run-1",
                "escalated_claim_ids": ["c1"],
                "interrupted_at": now - timedelta(hours=1),
                "last_reminder_at": None,
            },
            {
                "run_id": "run-2",
                "escalated_claim_ids": ["c2"],
                "interrupted_at": now - timedelta(hours=1),
                "last_reminder_at": None,
            },
        ]
    )

    service = PollingService(
        config=config,
        decision_checker=checker,
        graph_resumer=graph_resumer,
        reminder_writer=reminder_writer,
        runs_reader=runs_reader,
    )

    await service.poll_once()

    # run-2 should still be resumed even though run-1 failed
    assert "run-2" in graph_resumer.resumed_runs
    assert "run-1" not in graph_resumer.resumed_runs


@pytest.mark.anyio
async def test_poll_once_resume_failure_does_not_crash(
    config: PipelineConfig, now: datetime
):
    """If graph resume fails, poll_once should not crash."""
    decision_checker = MockDecisionChecker(completeness={"run-1": True})
    graph_resumer = FailingGraphResumer()
    reminder_writer = MockReminderWriter()
    runs_reader = MockPollableRunsReader(
        pending_runs=[
            {
                "run_id": "run-1",
                "escalated_claim_ids": ["c1"],
                "interrupted_at": now - timedelta(hours=1),
                "last_reminder_at": None,
            }
        ]
    )

    service = PollingService(
        config=config,
        decision_checker=decision_checker,
        graph_resumer=graph_resumer,
        reminder_writer=reminder_writer,
        runs_reader=runs_reader,
    )

    # Should not raise — errors are caught and logged
    await service.poll_once()


# --- Tests: start_polling and stop ---


@pytest.mark.anyio
async def test_start_polling_can_be_stopped(config: PipelineConfig):
    """start_polling should stop when stop() is called."""
    import anyio

    decision_checker = MockDecisionChecker()
    graph_resumer = MockGraphResumer()
    reminder_writer = MockReminderWriter()

    poll_count = 0

    class CountingRunsReader:
        async def get_pending_runs(self) -> list[dict]:
            nonlocal poll_count
            poll_count += 1
            return []

    runs_reader = CountingRunsReader()

    # Use very short poll interval for test speed
    fast_config: PipelineConfig = {**config, "poll_interval_seconds": 0.05}

    service = PollingService(
        config=fast_config,
        decision_checker=decision_checker,
        graph_resumer=graph_resumer,
        reminder_writer=reminder_writer,
        runs_reader=runs_reader,
    )

    # Start polling in background and stop after a short delay
    async def stop_after_delay():
        await anyio.sleep(0.1)
        service.stop()

    async with anyio.create_task_group() as tg:
        tg.start_soon(service.start_polling)
        tg.start_soon(stop_after_delay)

    # At least one poll should have happened
    assert poll_count >= 1
