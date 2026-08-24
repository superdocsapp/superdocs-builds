"""
Synthetic client roster for demos and tests.

Every client here is fabricated. Names are placeholder labels
("Client A" / generic first-name-only style), not real people.

This is the fictional data the task brief asks for:
"Fictional clients and fabricated test data are expected;
real third-party data is not welcome."
"""

from __future__ import annotations

import random
from datetime import date, timedelta

from .models import Assessment, Client, ProgramChange


def _drift(
    value: float,
    pct: float,
    rng: random.Random,
) -> float:
    """Move a value by roughly pct% in a plausible direction, with noise."""
    return round(
        value * (
            1
            + pct
            + rng.uniform(-0.01, 0.01)
        ),
        1,
    )


def make_synthetic_roster(
    n_clients: int = 8,
    seed: int = 42,
) -> list[Client]:
    """
    Build a roster of fictional fitness clients with baseline + 2 follow-ups.

    Each client gets a distinct trajectory:
      - fat loss
      - strength gain
      - plateau
      - regress then recover
      - mixed

    Batch output is therefore genuinely different per client.
    """

    rng = random.Random(seed)

    first_names = [
        "Alex",
        "Jordan",
        "Sam",
        "Riley",
        "Casey",
        "Morgan",
        "Taylor",
        "Jamie",
        "Drew",
        "Avery",
        "Quinn",
        "Reese",
        "Cameron",
        "Dakota",
        "Skyler",
        "Rowan",
        "Kendall",
        "Peyton",
        "Emerson",
        "Finley",
        "Harper",
        "Hayden",
        "Logan",
        "Parker",
        "River",
        "Sawyer",
        "Blake",
        "Elliot",
        "Jesse",
        "Kai",
        "Micah",
        "Noel",
        "Rory",
        "Sage",
        "Sloan",
        "Tatum",
        "Dallas",
        "Eden",
        "Lane",
        "Remy",
        "Shiloh",
        "Wren",
        "August",
        "Ellis",
        "Lennon",
    ]

    goals = [
        "Fat loss",
        "General strength",
        "Marathon prep",
        "Powerlifting meet prep",
        "Post-injury return to training",
        "Body recomposition",
    ]

    trajectories = [
        "fat_loss",
        "strength_gain",
        "plateau",
        "regress_then_recover",
        "mixed",
    ]

    training_frequencies = [
        "3 days/week",
        "4 days/week",
        "5 days/week",
    ]

    daily_step_goals = [
        7000,
        8000,
        9000,
        10000,
    ]

    clients: list[Client] = []

    start = date(2025, 3, 1)

    for i in range(n_clients):
        client_id = f"client-{i + 1:03d}"

        name = (
            f"{rng.choice(first_names)} "
            f"({client_id})"
        )

        goal = rng.choice(goals)

        trajectory = trajectories[
            i % len(trajectories)
        ]

        training_frequency = rng.choice(
            training_frequencies
        )

        daily_step_goal = rng.choice(
            daily_step_goals
        )

        baseline_vals = {
            "weight_kg": round(
                rng.uniform(62, 95),
                1,
            ),
            "body_fat_pct": round(
                rng.uniform(14, 32),
                1,
            ),
            "waist_cm": round(
                rng.uniform(70, 102),
                1,
            ),
            "resting_hr_bpm": round(
                rng.uniform(58, 78),
                0,
            ),
            "bench_1rm_kg": round(
                rng.uniform(35, 90),
                1,
            ),
            "squat_1rm_kg": round(
                rng.uniform(50, 130),
                1,
            ),
        }

        baseline_date = start + timedelta(days=i)

        assessments = [
            Assessment(
                assessment_date=baseline_date,
                values=dict(baseline_vals),
                adherence_pct=None,
                trainer_notes="Baseline intake assessment.",
            )
        ]

        program_changes: dict[
            int, list[ProgramChange]
        ] = {}

        next_goals: dict[
            int, list[str]
        ] = {}

        for block in (1, 2):
            previous = assessments[-1]
            values = dict(previous.values)

            # ---------------------------------------------------------
            # FAT LOSS TRAJECTORY
            # ---------------------------------------------------------
            if trajectory == "fat_loss":

                values["weight_kg"] = _drift(
                    values["weight_kg"],
                    -0.03 * block,
                    rng,
                )

                values["body_fat_pct"] = _drift(
                    values["body_fat_pct"],
                    -0.06 * block,
                    rng,
                )

                values["waist_cm"] = _drift(
                    values["waist_cm"],
                    -0.02 * block,
                    rng,
                )

                values["bench_1rm_kg"] = _drift(
                    values["bench_1rm_kg"],
                    0.01,
                    rng,
                )

                values["squat_1rm_kg"] = _drift(
                    values["squat_1rm_kg"],
                    0.01,
                    rng,
                )

                adherence = rng.uniform(75, 95)

            # ---------------------------------------------------------
            # STRENGTH GAIN TRAJECTORY
            # ---------------------------------------------------------
            elif trajectory == "strength_gain":

                values["bench_1rm_kg"] = _drift(
                    values["bench_1rm_kg"],
                    0.05 * block,
                    rng,
                )

                values["squat_1rm_kg"] = _drift(
                    values["squat_1rm_kg"],
                    0.06 * block,
                    rng,
                )

                values["weight_kg"] = _drift(
                    values["weight_kg"],
                    0.01 * block,
                    rng,
                )

                adherence = rng.uniform(80, 98)

            # ---------------------------------------------------------
            # PLATEAU TRAJECTORY
            # ---------------------------------------------------------
            elif trajectory == "plateau":

                for key in values:
                    values[key] = _drift(
                        values[key],
                        0.0,
                        rng,
                    )

                adherence = rng.uniform(55, 70)

            # ---------------------------------------------------------
            # REGRESS THEN RECOVER TRAJECTORY
            # ---------------------------------------------------------
            elif trajectory == "regress_then_recover":

                direction = (
                    -1
                    if block == 1
                    else 1
                )

                values["bench_1rm_kg"] = _drift(
                    values["bench_1rm_kg"],
                    direction * 0.04,
                    rng,
                )

                values["squat_1rm_kg"] = _drift(
                    values["squat_1rm_kg"],
                    direction * 0.04,
                    rng,
                )

                values["weight_kg"] = _drift(
                    values["weight_kg"],
                    direction * 0.02,
                    rng,
                )

                adherence = (
                    rng.uniform(40, 60)
                    if block == 1
                    else rng.uniform(70, 90)
                )

            # ---------------------------------------------------------
            # MIXED TRAJECTORY
            # ---------------------------------------------------------
            else:

                values["weight_kg"] = _drift(
                    values["weight_kg"],
                    -0.01 * block,
                    rng,
                )

                values["bench_1rm_kg"] = _drift(
                    values["bench_1rm_kg"],
                    0.02 * block,
                    rng,
                )

                values["resting_hr_bpm"] = _drift(
                    values["resting_hr_bpm"],
                    -0.02 * block,
                    rng,
                )

                adherence = rng.uniform(65, 90)

            # ---------------------------------------------------------
            # CREATE ASSESSMENT
            # ---------------------------------------------------------
            assessment_date = (
                baseline_date
                + timedelta(days=56 * block)
            )

            assessments.append(
                Assessment(
                    assessment_date=assessment_date,
                    values=values,
                    adherence_pct=round(
                        adherence,
                        0,
                    ),
                    trainer_notes=(
                        f"Block {block} re-assessment."
                    ),
                )
            )

            index = len(assessments) - 1

            # ---------------------------------------------------------
            # PROGRAM CHANGES
            # ---------------------------------------------------------
            if trajectory == "plateau":

                program_changes[index] = [
                    ProgramChange(
                        change=(
                            "Swapped linear progression "
                            "for a 3-week undulating wave"
                        ),
                        reason=(
                            "Three consecutive sessions "
                            "with no load or rep increase "
                            "on primary lifts"
                        ),
                    )
                ]

            elif (
                trajectory == "regress_then_recover"
                and block == 2
            ):

                program_changes[index] = [
                    ProgramChange(
                        change=(
                            "Reintroduced full training "
                            "volume after a deload block"
                        ),
                        reason=(
                            "Adherence and recovery markers "
                            "normalized after the prior "
                            "block's dip"
                        ),
                    )
                ]

            else:

                program_changes[index] = [
                    ProgramChange(
                        change=(
                            "Increased primary lift volume "
                            "by one working set per session"
                        ),
                        reason=(
                            "Consistent adherence and no "
                            "reported joint discomfort "
                            "in the prior block"
                        ),
                    )
                ]

            # ---------------------------------------------------------
            # NEXT BLOCK GOALS
            # ---------------------------------------------------------
            next_goals[index] = [
                (
                    "Progress "
                    f"{['bench press', 'back squat', 'deadlift'][block % 3]} "
                    "load by 2.5-5%"
                ),
                (
                    "Hold adherence at or above "
                    "this block's rate"
                ),
            ]

        # -------------------------------------------------------------
        # CREATE CLIENT
        # -------------------------------------------------------------
        clients.append(
            Client(
                client_id=client_id,
                display_name=name,
                goal=goal,
                assessments=assessments,
                program_changes_by_assessment=program_changes,
                next_block_goals=next_goals,
                training_frequency=training_frequency,
                daily_step_goal=daily_step_goal,
                status="Active",
            )
        )

    return clients