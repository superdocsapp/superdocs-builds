"""Credit calculations and scorecard arithmetic.

Every number that reaches a document is computed here, in Python, and covered
by tests. The language model writes prose; it never computes a total. This is
deliberate: models are unreliable at arithmetic and worse at keeping it correct
across successive edits, and the card is graded on the scorecard being right
*after* edits.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------- thresholds
# Each table is (threshold, points), ordered ascending. Sourced from the
# requirement documents in corpus/leed/ -- see each credit's Table.

WATER_POINTS = [(25, 1), (30, 2), (35, 3), (40, 4), (45, 5), (50, 6)]
ENERGY_POINTS = [(6, 1), (12, 3), (18, 5), (24, 7), (30, 9), (36, 11), (42, 13), (48, 15), (50, 18)]
WASTE_POINTS = [(50, 1), (75, 2)]

# LEED v4.1 BD+C certification bands, (minimum points, level).
CERTIFICATION_BANDS = [(80, "Platinum"), (60, "Gold"), (50, "Silver"), (40, "Certified")]


def points_for(percentage: float, table: list[tuple[float, int]]) -> int:
    """Highest points whose threshold the percentage meets. Below the lowest, zero."""
    earned = 0
    for threshold, points in table:
        if percentage >= threshold:
            earned = points
    return earned


def certification_level(points: int) -> str:
    """The band a point total falls in. Below 40 is not certified."""
    for minimum, level in CERTIFICATION_BANDS:
        if points >= minimum:
            return level
    return "Not certified"


def points_to_next_level(points: int) -> tuple[str, int] | None:
    """The next band up and the shortfall to reach it, or None at Platinum."""
    for minimum, level in reversed(CERTIFICATION_BANDS):
        if points < minimum:
            return level, minimum - points
    return None


# ------------------------------------------------------------------- results
@dataclass(frozen=True)
class CalcResult:
    """A calculation with its inputs preserved.

    The card requires "the calculation with its inputs shown", so inputs travel
    with the result rather than being discarded once the number is produced.
    """

    value: float
    unit: str
    points: int
    inputs: dict = field(default_factory=dict)
    steps: list[str] = field(default_factory=list)


# --------------------------------------------------------------- WE indoor water
def _daily_uses(group: dict) -> dict:
    """Per-person daily fixture uses for one occupant group.

    Male/female split is assumed 50/50, the standard default when a project
    has not established otherwise.
    """
    return {
        "wc": (float(group["wc_uses_male"]) + float(group["wc_uses_female"])) / 2,
        "urinal": float(group["urinal_uses_male"]) / 2,
        "lav": float(group["lav_uses"]),
        "shower": float(group["shower_uses"]),
        "kitchen": float(group["kitchen_minutes"]),
    }


def indoor_water_reduction(fixture_csv: Path, occupancy_csv: Path) -> CalcResult:
    """Annual indoor water use against the Table 1 baseline flow rates."""
    fixtures = {r["fixture_type"]: r for r in csv.DictReader(fixture_csv.open())}
    groups = list(csv.DictReader(occupancy_csv.open()))

    baseline_rates = {
        "wc": 1.6, "urinal": 1.0, "public_lav": 0.5,
        "private_lav": 2.2, "kitchen": 2.2, "shower": 2.5,
    }

    def installed(name: str, fallback: float) -> float:
        row = fixtures.get(name)
        return float(row["rated_flow"]) if row else fallback

    design_rates = {
        "wc": installed("Water closet", 1.6),
        "urinal": installed("Urinal", 1.0),
        "public_lav": installed("Public lavatory faucet", 0.5),
        "private_lav": installed("Private lavatory faucet", 2.2),
        "kitchen": installed("Kitchen faucet", 2.2),
        "shower": installed("Showerhead", 2.5),
    }

    # Lavatory uses split across public and private fixtures in proportion to
    # how many of each the schedule installs. The occupancy table records one
    # lav_uses figure per group and does not distinguish the two, so the split
    # is derived from the fixture counts already in evidence rather than
    # assumed -- and the private fixtures are counted, which matters because
    # their baseline-to-design delta (2.2 -> 1.20) is far larger than the
    # public one (0.5 -> 0.35).
    def _count(name: str) -> float:
        row = fixtures.get(name)
        return float(row["quantity"]) if row and row.get("quantity") else 0.0

    public_n, private_n = _count("Public lavatory faucet"), _count("Private lavatory faucet")
    lav_total = public_n + private_n
    public_share = public_n / lav_total if lav_total else 1.0
    private_share = private_n / lav_total if lav_total else 0.0

    baseline_gal = design_gal = 0.0
    for group in groups:
        count, days = float(group["count"]), float(group["days_per_year"])
        uses = _daily_uses(group)
        person_days = count * days
        for key, rate_key, share in (
            ("wc", "wc", 1.0), ("urinal", "urinal", 1.0),
            ("lav", "public_lav", public_share),
            ("lav", "private_lav", private_share),
            ("shower", "shower", 1.0), ("kitchen", "kitchen", 1.0),
        ):
            if not share:
                continue
            baseline_gal += person_days * uses[key] * share * baseline_rates[rate_key]
            design_gal += person_days * uses[key] * share * design_rates[rate_key]

    reduction = (baseline_gal - design_gal) / baseline_gal * 100 if baseline_gal else 0.0
    points = points_for(reduction, WATER_POINTS)

    return CalcResult(
        value=round(reduction, 2),
        unit="percent reduction",
        points=points,
        inputs={
            "baseline_annual_gallons": round(baseline_gal),
            "design_annual_gallons": round(design_gal),
            "occupant_groups": len(groups),
            "fixture_types": len(fixtures),
            "baseline_flow_rates": baseline_rates,
            "design_flow_rates": design_rates,
            "lavatory_split": {
                "public_fixtures": public_n,
                "private_fixtures": private_n,
                "public_share": round(public_share, 4),
                "private_share": round(private_share, 4),
            },
        },
        steps=[
            f"Baseline annual consumption: {baseline_gal:,.0f} gallons",
            f"Design annual consumption: {design_gal:,.0f} gallons",
            f"Reduction: ({baseline_gal:,.0f} - {design_gal:,.0f}) / {baseline_gal:,.0f} = {reduction:.2f}%",
            f"Table 2 threshold met: {points} point(s)",
        ],
    )


# ------------------------------------------------------------ EA energy performance
def energy_improvement(baseline_cost: float, proposed_cost: float) -> CalcResult:
    """Cost-based percentage improvement, per Appendix G."""
    improvement = (baseline_cost - proposed_cost) / baseline_cost * 100 if baseline_cost else 0.0
    points = points_for(improvement, ENERGY_POINTS)
    return CalcResult(
        value=round(improvement, 2),
        unit="percent improvement",
        points=points,
        inputs={"baseline_annual_cost": baseline_cost, "proposed_annual_cost": proposed_cost},
        steps=[
            f"Baseline annual energy cost: ${baseline_cost:,.0f}",
            f"Proposed annual energy cost: ${proposed_cost:,.0f}",
            f"Improvement: (${baseline_cost:,.0f} - ${proposed_cost:,.0f}) / ${baseline_cost:,.0f} = {improvement:.2f}%",
            f"Table 1 threshold met: {points} point(s)",
        ],
    )


# --------------------------------------------------------------- MR waste diversion
def waste_diversion(hauler_csv: Path) -> CalcResult:
    """Diversion by weight. Two points need 75% and four diverted streams."""
    rows = list(csv.DictReader(hauler_csv.open()))
    total = sum(float(r["tons"]) for r in rows)
    diverted_rows = [r for r in rows if r["facility_type"] == "recycling"]
    diverted = sum(float(r["tons"]) for r in diverted_rows)
    streams = sorted({r["material_stream"] for r in diverted_rows})

    percentage = diverted / total * 100 if total else 0.0
    points = points_for(percentage, WASTE_POINTS)

    # The stream-count condition is part of the requirement, not a separate
    # check: 2 points need four streams, 1 point needs three.
    if points == 2 and len(streams) < 4:
        points = 1
    if points >= 1 and len(streams) < 3:
        points = 0

    return CalcResult(
        value=round(percentage, 2),
        unit="percent diverted",
        points=points,
        inputs={
            "total_tons": round(total, 2),
            "diverted_tons": round(diverted, 2),
            "landfilled_tons": round(total - diverted, 2),
            "material_streams": streams,
            "stream_count": len(streams),
        },
        steps=[
            f"Total construction and demolition waste: {total:,.2f} tons",
            f"Diverted to recycling or salvage: {diverted:,.2f} tons",
            f"Diversion: {diverted:,.2f} / {total:,.2f} = {percentage:.2f}%",
            f"Material streams diverted: {len(streams)} ({', '.join(streams)})",
            f"Table 1 threshold met: {points} point(s)",
        ],
    )
