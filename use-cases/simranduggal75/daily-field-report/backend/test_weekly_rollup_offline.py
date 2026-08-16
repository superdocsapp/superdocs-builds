"""
Offline pytest tests for app.services.weekly_rollup. No network calls,
no SUPERDOCS_API_KEY required - build_weekly_rollup is pure
aggregation over fabricated report.json fixtures.
"""

import json
from datetime import date

from app.services.weekly_rollup import build_weekly_rollup, build_weekly_rollup_html


def _make_report(
    reports_dir,
    name,
    project,
    report_date,
    delays=None,
    work_by_area=None,
    headcount=None,
    safety=None,
):
    report_dir = reports_dir / name
    report_dir.mkdir()
    report_data = {
        "project": project,
        "report_date": report_date,
        "total_headcount": headcount,
        "manpower": [],
        "equipment": [],
        "work_by_area": work_by_area or [],
        "weather": None,
        "delays": delays or [],
        "safety_observations": safety or [],
        "source_notes": "x",
    }
    (report_dir / "report.json").write_text(json.dumps(report_data, indent=2), encoding="utf-8")
    metadata = {
        "report_id": name,
        "project": project,
        "report_date": report_date,
        "status": "awaiting_approval",
    }
    (report_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return report_dir


def _seeded_reports_dir(tmp_path):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()

    _make_report(
        reports_dir, "r1", "Riverside Tower", "2026-08-11",
        delays=[{"description": "Rain halted pour", "duration_hours": 2, "cause_category": "weather"}],
        work_by_area=[{"area": "Zone A", "work_performed": "Poured foundation", "status": "complete"}],
        headcount=18,
        safety=["All workers wore PPE"],
    )
    _make_report(
        reports_dir, "r2", "Riverside Tower", "2026-08-13",
        delays=[
            {"description": "Storm delayed crane ops", "duration_hours": 3, "cause_category": "weather"},
            {"description": "Excavator hydraulic failure", "duration_hours": 1.5, "cause_category": "equipment_failure"},
        ],
        work_by_area=[{"area": "Zone A", "work_performed": "Rebar placement", "status": "in_progress"}],
        headcount=20,
    )
    _make_report(
        reports_dir, "r3", "Riverside Tower", "2026-08-15",
        delays=[{"description": "Late material delivery", "duration_hours": 4, "cause_category": "material_delay"}],
        work_by_area=[{"area": "Zone B", "work_performed": "Site grading", "status": "complete"}],
    )
    # Out of range - must never appear in a 2026-08-10..16 rollup
    _make_report(reports_dir, "r4", "Riverside Tower", "2026-08-01", delays=[])
    # Different project - must never leak into a Riverside Tower rollup
    _make_report(
        reports_dir, "r5", "Harbor Bridge", "2026-08-12",
        delays=[{"description": "x", "cause_category": "weather"}],
    )

    return reports_dir


def test_rollup_multi_report_recurring_cause_is_grounded_and_scoped(tmp_path):
    reports_dir = _seeded_reports_dir(tmp_path)

    rollup = build_weekly_rollup(
        project="Riverside Tower",
        start_date=date(2026, 8, 10),
        end_date=date(2026, 8, 16),
        storage_dir=reports_dir,
    )

    assert rollup["report_count"] == 3
    assert {r["report_id"] for r in rollup["reports"]} == {"r1", "r2", "r3"}

    recurring_categories = {c["cause_category"] for c in rollup["recurring_delay_causes"]}
    assert recurring_categories == {"weather"}

    weather_bucket = next(c for c in rollup["recurring_delay_causes"] if c["cause_category"] == "weather")
    assert weather_bucket["distinct_report_count"] == 2
    report_ids_for_weather = {o["report_id"] for o in weather_bucket["occurrences"]}
    assert report_ids_for_weather == {"r1", "r2"}

    assert set(rollup["progress_summary"]["work_by_area"].keys()) == {"Zone A", "Zone B"}
    assert len(rollup["progress_summary"]["headcount_by_date"]) == 2
    assert len(rollup["progress_summary"]["safety_observations"]) == 1


def test_rollup_html_excludes_out_of_range_and_other_projects(tmp_path):
    reports_dir = _seeded_reports_dir(tmp_path)

    rollup = build_weekly_rollup(
        project="Riverside Tower",
        start_date=date(2026, 8, 10),
        end_date=date(2026, 8, 16),
        storage_dir=reports_dir,
    )
    html = build_weekly_rollup_html(rollup)

    assert "r1" in html and "r2" in html and "r3" in html
    assert "r4" not in html
    assert "r5" not in html
    assert "Harbor Bridge" not in html


def test_rollup_empty_range_states_no_data_explicitly(tmp_path):
    reports_dir = _seeded_reports_dir(tmp_path)

    rollup = build_weekly_rollup(
        project="Riverside Tower",
        start_date=date(2020, 1, 1),
        end_date=date(2020, 1, 7),
        storage_dir=reports_dir,
    )

    assert rollup["report_count"] == 0
    assert rollup["recurring_delay_causes"] == []
    assert "No processed reports found" in rollup["grounding_note"]

    html = build_weekly_rollup_html(rollup)
    assert "No processed reports found" in html


def test_rollup_single_report_week_never_claims_a_recurring_trend(tmp_path):
    reports_dir = _seeded_reports_dir(tmp_path)

    rollup = build_weekly_rollup(
        project="Riverside Tower",
        start_date=date(2026, 8, 11),
        end_date=date(2026, 8, 11),
        storage_dir=reports_dir,
    )

    assert rollup["report_count"] == 1
    assert rollup["recurring_delay_causes"] == []
    assert "recurrence needs at least 2" in rollup["recurrence_note"]


def test_rollup_unknown_project_yields_zero_reports_not_a_guess(tmp_path):
    reports_dir = _seeded_reports_dir(tmp_path)

    rollup = build_weekly_rollup(
        project="Nonexistent Project",
        start_date=date(2026, 8, 10),
        end_date=date(2026, 8, 16),
        storage_dir=reports_dir,
    )

    assert rollup["report_count"] == 0
