"""
Data models for the Client Progress & Re-Assessment Report builder.

All client data in this repository is synthetic / fictional, generated in
fixtures.py. No real client, real trainer, or real gym data is used anywhere
in this project (see README > Data & Privacy).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional


# Metrics we track. Keep this list small and named, not a free-form dict,
# so a typo in a metric name fails loudly instead of silently vanishing
# from a chart or table.
METRICS = [
    ("weight_kg", "Weight", "kg"),
    ("body_fat_pct", "Body Fat", "%"),
    ("waist_cm", "Waist", "cm"),
    ("resting_hr_bpm", "Resting HR", "bpm"),
    ("bench_1rm_kg", "Bench 1RM", "kg"),
    ("squat_1rm_kg", "Squat 1RM", "kg"),
]

METRIC_KEYS = [m[0] for m in METRICS]


@dataclass
class Assessment:
    """One point-in-time measurement snapshot for a client."""

    assessment_date: date
    values: dict[str, float]
    adherence_pct: Optional[float] = None
    trainer_notes: str = ""

    def get(self, metric_key: str) -> Optional[float]:
        return self.values.get(metric_key)


@dataclass
class ProgramChange:
    """A single change made to the client's programme, with a stated reason."""

    change: str
    reason: str


@dataclass
class Client:
    """A fictional coaching client and their full assessment history."""

    client_id: str
    display_name: str
    goal: str

    assessments: list[Assessment] = field(default_factory=list)

    program_changes_by_assessment: dict[
        int, list[ProgramChange]
    ] = field(default_factory=dict)

    next_block_goals: dict[
        int, list[str]
    ] = field(default_factory=dict)

    # Baseline programme information.
    # Defaults keep existing tests and callers backwards-compatible.
    training_frequency: Optional[str] = None
    daily_step_goal: Optional[int] = None
    status: str = "Active"

    def baseline(self) -> Assessment:
        if not self.assessments:
            raise ValueError(
                f"Client {self.client_id} has no assessments yet"
            )
        return self.assessments[0]

    def latest(self) -> Assessment:
        if not self.assessments:
            raise ValueError(
                f"Client {self.client_id} has no assessments yet"
            )
        return self.assessments[-1]

    def previous(self) -> Optional[Assessment]:
        return (
            self.assessments[-2]
            if len(self.assessments) >= 2
            else None
        )

    def is_reassessment(self) -> bool:
        """True once there's a second assessment to compare against baseline."""
        return len(self.assessments) >= 2

    def series(
        self,
        metric_key: str,
    ) -> tuple[list[date], list[float]]:
        """Dates and values for one metric across all assessments that have it."""

        dates: list[date] = []
        values: list[float] = []

        for assessment in self.assessments:
            value = assessment.get(metric_key)

            if value is not None:
                dates.append(assessment.assessment_date)
                values.append(value)

        return dates, values