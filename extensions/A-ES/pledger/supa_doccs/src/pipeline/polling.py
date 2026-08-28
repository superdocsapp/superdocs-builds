"""Human review polling service — monitors decisions and triggers graph resume.

This service periodically checks whether all escalated items for pending runs
have received human decisions. When all decisions are received, it triggers
the LangGraph resume API. It also inserts reminder audit events at configured
intervals for overdue items.

Dependency injection is used for all external interactions (decision checking,
graph resuming, reminder writing, pending runs reading) to enable unit testing
without requiring database or LangGraph infrastructure.
"""

from __future__ import annotations

import anyio
import logging
from datetime import datetime, timezone
from typing import Protocol

from src.pipeline.config import PipelineConfig

logger = logging.getLogger(__name__)


# --- Dependency Protocols ---


class DecisionChecker(Protocol):
    """Protocol for checking if all decisions have been received for a run."""

    async def check_completeness(self, run_id: str) -> bool:
        """Check if all decisions have been received for a run's escalated items.

        Args:
            run_id: The pipeline run ID to check.

        Returns:
            True if all escalated items have received decisions, False otherwise.
        """
        ...


class GraphResumer(Protocol):
    """Protocol for resuming the graph execution for a completed run."""

    async def resume(self, run_id: str) -> None:
        """Resume the graph execution for a completed run.

        Args:
            run_id: The pipeline run ID to resume.
        """
        ...


class ReminderWriter(Protocol):
    """Protocol for inserting reminder audit events for unresolved items."""

    async def write_reminder(self, run_id: str, claim_ids: list[str]) -> None:
        """Insert reminder audit events for unresolved items.

        Args:
            run_id: The pipeline run ID.
            claim_ids: List of claim IDs that are still pending.
        """
        ...


class PollableRunsReader(Protocol):
    """Protocol for reading runs that are waiting for human review."""

    async def get_pending_runs(self) -> list[dict]:
        """Get all runs with status 'running' that are waiting for human review.

        Returns:
            List of dicts with at minimum:
              - "run_id": str
              - "escalated_claim_ids": list[str]
              - "interrupted_at": datetime (when the interrupt was triggered)
              - "last_reminder_at": datetime | None (last reminder time)
        """
        ...


# --- Polling Service ---


class PollingService:
    """Service that polls for completed human reviews and triggers graph resume.

    The service checks all pending runs at a configurable interval, resumes
    any that have received all decisions, and sends reminders for overdue items.
    """

    def __init__(
        self,
        *,
        config: PipelineConfig,
        decision_checker: DecisionChecker,
        graph_resumer: GraphResumer,
        reminder_writer: ReminderWriter,
        runs_reader: PollableRunsReader,
    ) -> None:
        """Initialize the polling service.

        Args:
            config: Pipeline configuration with poll_interval_seconds and
                reminder_interval_hours.
            decision_checker: Checks if all decisions are received for a run.
            graph_resumer: Resumes graph execution for a run.
            reminder_writer: Writes reminder audit events.
            runs_reader: Reads pending runs waiting for human review.
        """
        self._config = config
        self._decision_checker = decision_checker
        self._graph_resumer = graph_resumer
        self._reminder_writer = reminder_writer
        self._runs_reader = runs_reader
        self._running = False

    async def poll_once(self) -> None:
        """Execute a single polling cycle.

        1. Get all pending runs waiting for human review.
        2. For each run, check if all decisions have been received.
        3. If complete, call the graph resume API.
        4. If overdue (past reminder_interval_hours since last reminder),
           insert reminder audit events.
        """
        pending_runs = await self._runs_reader.get_pending_runs()

        for run_info in pending_runs:
            run_id: str = run_info["run_id"]
            escalated_claim_ids: list[str] = run_info["escalated_claim_ids"]
            interrupted_at: datetime = run_info["interrupted_at"]
            last_reminder_at: datetime | None = run_info.get("last_reminder_at")

            try:
                # Check if all decisions have been received
                is_complete = await self._decision_checker.check_completeness(
                    run_id
                )

                if is_complete:
                    # All decisions received — resume the graph
                    await self._graph_resumer.resume(run_id)
                    logger.info(
                        "Resumed run %s — all decisions received", run_id
                    )
                else:
                    # Check if a reminder is due
                    await self._maybe_send_reminder(
                        run_id=run_id,
                        claim_ids=escalated_claim_ids,
                        interrupted_at=interrupted_at,
                        last_reminder_at=last_reminder_at,
                    )
            except Exception:
                logger.exception(
                    "Error processing pending run %s during poll", run_id
                )

    async def _maybe_send_reminder(
        self,
        *,
        run_id: str,
        claim_ids: list[str],
        interrupted_at: datetime,
        last_reminder_at: datetime | None,
    ) -> None:
        """Send a reminder if enough time has elapsed since the last one.

        Reminders are sent at config["reminder_interval_hours"] intervals,
        starting from the interrupt time.
        """
        now = datetime.now(timezone.utc)
        reminder_interval_hours = self._config["reminder_interval_hours"]

        # Determine the reference time for the next reminder
        reference_time = last_reminder_at if last_reminder_at else interrupted_at

        hours_since_reference = (
            now - reference_time
        ).total_seconds() / 3600.0

        if hours_since_reference >= reminder_interval_hours:
            await self._reminder_writer.write_reminder(run_id, claim_ids)
            logger.info(
                "Sent reminder for run %s — %d unresolved claims",
                run_id,
                len(claim_ids),
            )

    async def start_polling(self) -> None:
        """Run poll_once in a loop with config["poll_interval_seconds"] delay.

        This method runs indefinitely until stop() is called. It is designed
        to be run as an async task.
        """
        self._running = True
        poll_interval = self._config["poll_interval_seconds"]

        while self._running:
            try:
                await self.poll_once()
            except Exception:
                logger.exception("Unhandled error during polling cycle")

            await anyio.sleep(poll_interval)

    def stop(self) -> None:
        """Signal the polling loop to stop after the current cycle."""
        self._running = False
