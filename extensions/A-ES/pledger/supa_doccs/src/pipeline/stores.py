"""Database-backed store implementations for the pipeline API.

Provides production implementations of RunStore, ResumeStore, HistoryStore,
and CostStore protocols, backed by SQLAlchemy sessions.
"""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from src.models.runs import Run, RunStep
from src.pipeline.serialization import deserialize_state, serialize_state


class SQLRunStore:
    """SQLAlchemy-backed implementation of the RunStore protocol."""

    def __init__(self, session_factory):
        self._session_factory = session_factory

    def create_run(
        self, run_id: str, document_id: str, document_version_id: str, config_snapshot: dict
    ) -> None:
        with self._session_factory() as session:
            run = Run(
                id=uuid.UUID(run_id),
                status="pending",
                config_snapshot={
                    **config_snapshot,
                    "document_id": document_id,
                    "document_version_id": document_version_id,
                },
                initiator="api",
                version=1,
            )
            session.add(run)
            session.commit()

    def acquire_run_lock(self, run_id: str) -> bool:
        """Always succeeds for now (single-process demo)."""
        return True

    def run_exists(self, run_id: str) -> bool:
        with self._session_factory() as session:
            result = session.execute(
                select(Run).where(Run.id == uuid.UUID(run_id))
            ).scalar_one_or_none()
            return result is not None


class SQLResumeStore:
    """SQLAlchemy-backed resume store for reading checkpoint state."""

    def __init__(self, session_factory):
        self._session_factory = session_factory

    def get_last_checkpoint(self, run_id: str) -> Optional[dict[str, Any]]:
        with self._session_factory() as session:
            step = session.execute(
                select(RunStep)
                .where(
                    RunStep.run_id == uuid.UUID(run_id),
                    RunStep.status.in_(["completed", "skipped"]),
                )
                .order_by(RunStep.step_order.desc())
                .limit(1)
            ).scalar_one_or_none()

            if step is None:
                return None

            return {
                "step_name": step.step_name,
                "step_order": step.step_order,
                "output_state": step.output_state,
                "status": step.status,
            }

    def get_run_state(self, run_id: str) -> Optional[dict[str, Any]]:
        """Get current pipeline state for the canvas from the latest checkpoint."""
        with self._session_factory() as session:
            # Get the run
            run = session.execute(
                select(Run).where(Run.id == uuid.UUID(run_id))
            ).scalar_one_or_none()
            if run is None:
                return None

            # Get latest step
            step = session.execute(
                select(RunStep)
                .where(RunStep.run_id == uuid.UUID(run_id))
                .order_by(RunStep.step_order.desc())
                .limit(1)
            ).scalar_one_or_none()

            if step is None:
                # Run exists but no steps yet
                return {
                    "run_id": run_id,
                    "current_node": "",
                    "node_status": "pending",
                    "completed_nodes": [],
                    "skipped_nodes": [],
                    "retries": {},
                    "error_type": None,
                    "error_detail": None,
                    "run_status": run.status,
                }

            # Read state from the step's output
            state = step.output_state or {}
            return {
                "run_id": run_id,
                "current_node": state.get("current_node", step.step_name),
                "node_status": state.get("node_status", step.status),
                "completed_nodes": state.get("completed_nodes", []),
                "skipped_nodes": state.get("skipped_nodes", []),
                "retries": state.get("retries", {}),
                "error_type": state.get("error_type"),
                "error_detail": state.get("error_detail"),
                "run_status": run.status,
            }

    def acquire_run_lock(self, run_id: str) -> bool:
        return True

    def mark_orphaned_running_as_failed(self, run_id: str) -> int:
        with self._session_factory() as session:
            result = session.execute(
                update(RunStep)
                .where(
                    RunStep.run_id == uuid.UUID(run_id),
                    RunStep.status == "running",
                    RunStep.ended_at.is_(None),
                )
                .values(status="failed", error_details="interrupted")
            )
            session.commit()
            return result.rowcount  # type: ignore[return-value]


class SQLHistoryStore:
    """History store backed by the audit_events table.

    Thin alias over history_sql.SQLHistoryStore (kept here because
    stores.py is the canonical store registry).
    """

    def __init__(self, session_factory):
        from src.pipeline.history_sql import SQLHistoryStore as _Impl

        self._impl = _Impl(session_factory)

    def get_events_for_run(self, run_id: str):
        return self._impl.get_events_for_run(run_id)


class SQLCostStore:
    """SQLAlchemy-backed cost store reading from run_steps.

    Durable: costs live in the run_steps table, so they survive API
    process restarts — same durability contract as the history store.
    """

    def __init__(self, session_factory):
        self._session_factory = session_factory

    def get_step_costs(self, run_id: str) -> list[dict[str, Any]]:
        """Per-step cost rows for a run (CostStore protocol)."""
        with self._session_factory() as session:
            steps = session.execute(
                select(RunStep)
                .where(RunStep.run_id == uuid.UUID(run_id))
                .order_by(RunStep.step_order)
            ).scalars().all()

            return [
                {
                    "step_name": step.step_name,
                    "step_order": step.step_order,
                    "status": step.status,
                    "duration_ms": step.duration_ms,
                    "input_tokens": step.input_tokens,
                    "output_tokens": step.output_tokens,
                    "cost_usd": float(step.cost_usd)
                    if step.cost_usd is not None
                    else None,
                }
                for step in steps
            ]

    def get_run_cost(self, run_id: str) -> dict[str, Any]:
        with self._session_factory() as session:
            steps = session.execute(
                select(RunStep)
                .where(RunStep.run_id == uuid.UUID(run_id))
                .order_by(RunStep.step_order)
            ).scalars().all()

            stages = []
            total_duration = 0
            total_input_tokens = 0
            total_output_tokens = 0
            total_cost = 0.0

            for step in steps:
                duration = step.duration_ms or 0
                inp = step.input_tokens or 0
                out = step.output_tokens or 0
                cost = float(step.cost_usd or 0)
                total_duration += duration
                total_input_tokens += inp
                total_output_tokens += out
                total_cost += cost

                stages.append({
                    "stage": step.step_name,
                    "step_order": step.step_order,
                    "status": step.status,
                    "duration_ms": duration,
                    "input_tokens": inp,
                    "output_tokens": out,
                    "cost_usd": cost,
                })

            return {
                "run_id": run_id,
                "total_duration_ms": total_duration,
                "total_input_tokens": total_input_tokens,
                "total_output_tokens": total_output_tokens,
                "total_cost_usd": total_cost,
                "stages": stages,
            }


class InMemoryExecutorStore:
    """In-memory executor store for the demo pipeline execution.

    Stores checkpoints in memory and also writes to the DB for the
    state endpoint to read.
    """

    def __init__(self, session_factory):
        self._session_factory = session_factory
        self._checkpoints: dict[str, list[dict]] = {}
        self._locks: dict[str, threading.Lock] = {}

    def create_step(self, run_id: str, step_name: str, step_order: int) -> None:
        with self._session_factory() as session:
            step = RunStep(
                id=uuid.uuid4(),
                run_id=uuid.UUID(run_id),
                step_name=step_name,
                step_order=step_order,
                status="running",
                started_at=datetime.now(timezone.utc),
                input_state={},
                output_state={},
            )
            session.add(step)
            session.commit()

    def write_checkpoint(
        self,
        run_id: str,
        step_name: str,
        step_order: int,
        output_state: dict[str, Any],
        status: str,
        ended_at: Any,
        duration_ms: Optional[int] = None,
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
        cost_usd: Optional[float] = None,
    ) -> None:
        # Update the DB step row
        with self._session_factory() as session:
            step = session.execute(
                select(RunStep).where(
                    RunStep.run_id == uuid.UUID(run_id),
                    RunStep.step_name == step_name,
                )
            ).scalar_one_or_none()

            if step:
                step.output_state = output_state
                step.status = status
                step.ended_at = ended_at
                step.duration_ms = duration_ms
                step.input_tokens = input_tokens
                step.output_tokens = output_tokens
                step.cost_usd = cost_usd
                session.commit()

        # In-memory checkpoint
        if run_id not in self._checkpoints:
            self._checkpoints[run_id] = []
        self._checkpoints[run_id].append({
            "step_name": step_name,
            "step_order": step_order,
            "output_state": output_state,
            "status": status,
        })

    def get_last_checkpoint(self, run_id: str) -> Optional[dict[str, Any]]:
        steps = self._checkpoints.get(run_id, [])
        completed = [s for s in steps if s["status"] in ("completed", "skipped")]
        if not completed:
            return None
        return max(completed, key=lambda s: s["step_order"])

    def mark_orphaned_running_as_failed(self, run_id: str) -> int:
        return 0

    def acquire_run_lock(self, run_id: str) -> bool:
        if run_id not in self._locks:
            self._locks[run_id] = threading.Lock()
        return self._locks[run_id].acquire(blocking=False)

    def release_run_lock(self, run_id: str) -> None:
        if run_id in self._locks:
            try:
                self._locks[run_id].release()
            except RuntimeError:
                pass
