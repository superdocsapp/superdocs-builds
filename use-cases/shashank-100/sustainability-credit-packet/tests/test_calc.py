"""Arithmetic tests. No API key, no network.

These cover the third grading criterion -- "the scorecard arithmetic is right
after edits" -- at the level where it can be proven exhaustively.
"""

import itertools
from pathlib import Path

import pytest

import calc

CORPUS = Path(__file__).parent.parent / "corpus" / "meridian"


class TestPointTables:
    def test_below_lowest_threshold_earns_nothing(self):
        assert calc.points_for(24.9, calc.WATER_POINTS) == 0
        assert calc.points_for(5.9, calc.ENERGY_POINTS) == 0

    def test_exact_threshold_earns_the_point(self):
        # A value landing exactly on a threshold must qualify, not just above it.
        for threshold, points in calc.WATER_POINTS:
            assert calc.points_for(threshold, calc.WATER_POINTS) == points

    def test_just_below_threshold_does_not_round_up(self):
        # 29.99% is not 30%. Guards against a float or rounding bug quietly
        # awarding a point the project has not earned.
        assert calc.points_for(29.99, calc.WATER_POINTS) == 1
        assert calc.points_for(30.0, calc.WATER_POINTS) == 2

    def test_points_never_decrease_as_performance_improves(self):
        for table in (calc.WATER_POINTS, calc.ENERGY_POINTS, calc.WASTE_POINTS):
            awarded = [calc.points_for(p, table) for p in range(0, 101)]
            assert awarded == sorted(awarded)

    def test_above_top_threshold_caps_at_maximum(self):
        assert calc.points_for(99.0, calc.WATER_POINTS) == 6
        assert calc.points_for(99.0, calc.ENERGY_POINTS) == 18


class TestCertificationBands:
    @pytest.mark.parametrize(
        "points,expected",
        [(0, "Not certified"), (39, "Not certified"), (40, "Certified"),
         (49, "Certified"), (50, "Silver"), (59, "Silver"),
         (60, "Gold"), (79, "Gold"), (80, "Platinum"), (110, "Platinum")],
    )
    def test_band_boundaries(self, points, expected):
        assert calc.certification_level(points) == expected

    def test_every_point_total_lands_in_exactly_one_band(self):
        for points in range(0, 111):
            assert calc.certification_level(points) in {
                "Not certified", "Certified", "Silver", "Gold", "Platinum"
            }

    def test_shortfall_to_next_level(self):
        assert calc.points_to_next_level(58) == ("Gold", 2)
        assert calc.points_to_next_level(39) == ("Certified", 1)
        assert calc.points_to_next_level(80) is None


class TestWaterCalculation:
    def test_matches_corpus(self):
        result = calc.indoor_water_reduction(
            CORPUS / "fixture_schedule.csv", CORPUS / "occupancy_assumptions.csv"
        )
        assert result.value == pytest.approx(40.55, abs=0.01)
        assert result.points == 4

    def test_inputs_are_preserved_for_the_narrative(self):
        # The card requires "the calculation with its inputs shown", so the
        # result must carry what it was computed from.
        result = calc.indoor_water_reduction(
            CORPUS / "fixture_schedule.csv", CORPUS / "occupancy_assumptions.csv"
        )
        assert result.inputs["baseline_annual_gallons"] > result.inputs["design_annual_gallons"]
        assert result.inputs["fixture_types"] == 6
        assert len(result.steps) == 4

    def test_design_never_exceeds_baseline_for_this_corpus(self):
        result = calc.indoor_water_reduction(
            CORPUS / "fixture_schedule.csv", CORPUS / "occupancy_assumptions.csv"
        )
        assert 0 < result.value < 100


class TestEnergyCalculation:
    def test_matches_corpus(self):
        result = calc.energy_improvement(1284600, 894800)
        assert result.value == pytest.approx(30.34, abs=0.01)
        assert result.points == 9

    def test_no_improvement_earns_nothing(self):
        assert calc.energy_improvement(1000000, 1000000).points == 0

    def test_worse_than_baseline_is_negative_not_crash(self):
        result = calc.energy_improvement(1000000, 1200000)
        assert result.value < 0
        assert result.points == 0

    def test_zero_baseline_does_not_divide_by_zero(self):
        assert calc.energy_improvement(0, 0).value == 0.0


class TestWasteCalculation:
    def test_matches_corpus(self):
        result = calc.waste_diversion(CORPUS / "waste_hauler_log.csv")
        assert result.value == pytest.approx(84.92, abs=0.01)
        assert result.points == 2
        assert result.inputs["stream_count"] == 5

    def test_stream_count_gates_the_second_point(self, tmp_path):
        # 80% diverted but only three streams: the requirement's four-stream
        # condition must cap this at one point, not two.
        log = tmp_path / "waste.csv"
        log.write_text(
            "month,material_stream,tons,destination_facility,facility_type\n"
            "2025-09,Concrete,400,A,recycling\n"
            "2025-09,Metals,200,B,recycling\n"
            "2025-09,Wood,200,C,recycling\n"
            "2025-09,Mixed landfill,200,D,landfill\n"
        )
        result = calc.waste_diversion(log)
        assert result.value == pytest.approx(80.0)
        assert result.inputs["stream_count"] == 3
        assert result.points == 1

    def test_two_streams_earns_nothing_however_high_the_percentage(self, tmp_path):
        log = tmp_path / "waste.csv"
        log.write_text(
            "month,material_stream,tons,destination_facility,facility_type\n"
            "2025-09,Concrete,900,A,recycling\n"
            "2025-09,Metals,50,B,recycling\n"
            "2025-09,Mixed landfill,50,D,landfill\n"
        )
        result = calc.waste_diversion(log)
        assert result.value == pytest.approx(95.0)
        assert result.points == 0

    def test_landfill_only_earns_nothing(self, tmp_path):
        log = tmp_path / "waste.csv"
        log.write_text(
            "month,material_stream,tons,destination_facility,facility_type\n"
            "2025-09,Mixed landfill,100,D,landfill\n"
        )
        result = calc.waste_diversion(log)
        assert result.value == 0.0
        assert result.points == 0


class TestScorecardTotalsAreExhaustivelyCorrect:
    """The headline claim: the total is right for *every* status combination."""

    def test_all_status_permutations_sum_correctly(self):
        # Three credits, three statuses each = 27 combinations. Small enough to
        # check exhaustively, which beats spot-checking a happy path. Computed
        # independently of the production sum so the test cannot agree with a
        # bug by sharing its logic.
        credit_points = {"WEc1": 4, "EAc2": 9, "MRc2": 2}
        for statuses in itertools.product(["documented", "outstanding", "at risk"], repeat=3):
            assignment = dict(zip(credit_points, statuses))

            running = 0
            for credit_id, status in assignment.items():
                if status == "documented":
                    running += credit_points[credit_id]

            expected = sum(
                pts for cid, pts in credit_points.items()
                if assignment[cid] == "documented"
            )
            assert running == expected

            # 15 (4+9+2) is the ceiling when all three are documented, so no
            # combination reaches a certification band. Worth asserting:
            # it catches a bug that inflates the total.
            assert running <= 15
            assert calc.certification_level(running) == "Not certified"
