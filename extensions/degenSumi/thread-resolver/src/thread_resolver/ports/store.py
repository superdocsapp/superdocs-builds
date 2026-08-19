"""The seam for run state that outlives the process.

State is written after every stage so that a run killed mid-flight resumes from
the last completed stage rather than from the beginning. Anything already paid
for stays paid for.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from thread_resolver.domain.run import RunState


@runtime_checkable
class RunStore(Protocol):
    def save(self, state: RunState) -> None:
        """Persist the run, replacing any earlier state for the same run id.

        Must be atomic: a process killed during a save leaves the previously
        saved state readable rather than a truncated record.
        """
        ...

    def load(self, run_id: str) -> RunState | None:
        """The stored run, or None when nothing has been saved for that id."""
        ...

    def list_runs(self) -> tuple[RunState, ...]:
        """Every stored run, most recently saved first."""
        ...
