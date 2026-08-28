"""Cooperative cancellation for pipeline runs.

Provides an in-memory cancellation registry that executors check between
node transitions. Setting the flag does NOT delete checkpoints or audit
events — it only signals the executor to stop cleanly after the current
node finishes.

Semantics:
- A cancelled run retains all completed checkpoints.
- A cancelled run can be resumed later via POST /runs/{id}/resume.
- The run status is set to "cancelled" in the DB when the executor
  observes the flag.
"""

from __future__ import annotations

import threading
from typing import Optional


# Thread-safe set of run_ids that have been signalled for cancellation.
_cancel_lock = threading.Lock()
_cancelled_runs: set[str] = set()


def request_cancel(run_id: str) -> None:
    """Signal that a run should be cancelled cooperatively.

    The executor checks this flag between nodes and stops cleanly.
    """
    with _cancel_lock:
        _cancelled_runs.add(run_id)


def is_cancelled(run_id: str) -> bool:
    """Check whether a cancellation has been requested for this run."""
    with _cancel_lock:
        return run_id in _cancelled_runs


def clear_cancel(run_id: str) -> None:
    """Clear the cancellation flag for a run (e.g. on resume).

    Called when a run is resumed so that the new execution is not
    immediately stopped by a stale flag.
    """
    with _cancel_lock:
        _cancelled_runs.discard(run_id)


def reset_all() -> None:
    """Clear all cancellation flags. Used in tests."""
    with _cancel_lock:
        _cancelled_runs.clear()
