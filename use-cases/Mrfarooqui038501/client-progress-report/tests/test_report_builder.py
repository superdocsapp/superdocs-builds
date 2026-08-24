"""
Unit tests for report_builder module.

Verifies:
  - delta calculation and directional scoring ('improved' / 'regressed' / 'no change')
  - deterministic comparison table HTML construction
  - adherence line formatting (present vs not recorded)
  - baseline instruction generation with strict anti-placeholder directives
  - narrative prompt generation with fact grounding and 80-word constraint
  - combined report section HTML assembly with embedded chart URL
"""
from datetime import date

from src.models import Assessment, Client, ProgramChange
from src.report_builder import (
    _delta_str,
    build_adherence_line,
    build_baseline_instruction,
    build_comparison_table_html,
    build_narrative_instruction,
    build_report_section_html,
)


def test_delta_str_higher_is_better():
    # Bench press increase = improved
    assert _delta_str(50.0, 55.0, higher_is_better=True) == "+5.0 \u2191 (improved)"
    # Bench press decrease = regressed
    assert _delta_str(55.0, 50.0, higher_is_better=True) == "-5.0 \u2193 (regressed)"
    # No change
    assert _delta_str(50.0, 50.0, higher_is_better=True) == "no change"


def test_delta_str_lower_is_better():
    # Weight decrease = improved
    assert _delta_str(80.0, 76.0, higher_is_better=False) == "-4.0 \u2193 (improved)"
    # Weight increase = regressed
    assert _delta_str(76.0, 80.0, higher_is_better=False) == "+4.0 \u2191 (regressed)"
    # No change
    assert _delta_str(76.0, 76.0, higher_is_better=False) == "no change"


def test_build_comparison_table_html_structure():
    client = Client(
        client_id="client-001",
        display_name="Alex (client-001)",
        goal="Fat loss",
        assessments=[
            Assessment(
                assessment_date=date(2025, 1, 1),
                values={"weight_kg": 80.0, "body_fat_pct": 22.0, "bench_1rm_kg": 60.0},
            ),
            Assessment(
                assessment_date=date(2025, 3, 1),
                values={"weight_kg": 76.0, "body_fat_pct": 20.0, "bench_1rm_kg": 65.0},
            ),
        ],
    )
    html = build_comparison_table_html(client)

    assert '<table data-report-section="comparison-table">' in html
    assert "Baseline (2025-01-01)" in html
    assert "Current (2025-03-01)" in html
    # Weight row: 80.0 kg -> 76.0 kg (-4.0 improved)
    assert "<td>Weight</td><td>80.0 kg</td><td>76.0 kg</td><td>-4.0 \u2193 (improved)</td>" in html
    # Body Fat row: 22.0 % -> 20.0 % (-2.0 improved)
    assert "<td>Body Fat</td><td>22.0 %</td><td>20.0 %</td><td>-2.0 \u2193 (improved)</td>" in html
    # Bench 1RM row: 60.0 kg -> 65.0 kg (+5.0 improved)
    assert "<td>Bench 1RM</td><td>60.0 kg</td><td>65.0 kg</td><td>+5.0 \u2191 (improved)</td>" in html


def test_build_comparison_table_html_skips_missing_metrics():
    client = Client(
        client_id="client-001",
        display_name="Alex (client-001)",
        goal="Fat loss",
        assessments=[
            Assessment(
                assessment_date=date(2025, 1, 1),
                values={"weight_kg": 80.0, "waist_cm": 85.0},
            ),
            Assessment(
                assessment_date=date(2025, 3, 1),
                values={"weight_kg": 78.0},  # waist_cm missing in current
            ),
        ],
    )
    html = build_comparison_table_html(client)
    assert "Weight" in html
    assert "Waist" not in html


def test_build_adherence_line_with_and_without_data():
    # Present adherence
    client_with_adh = Client(
        client_id="client-001",
        display_name="Alex",
        goal="Fat loss",
        assessments=[
            Assessment(assessment_date=date(2025, 1, 1), values={}, adherence_pct=None),
            Assessment(assessment_date=date(2025, 3, 1), values={}, adherence_pct=92.4),
        ],
    )
    line = build_adherence_line(client_with_adh)
    assert "92% of prescribed sessions completed" in line

    # Missing adherence
    client_no_adh = Client(
        client_id="client-002",
        display_name="Sam",
        goal="Strength",
        assessments=[
            Assessment(assessment_date=date(2025, 1, 1), values={}, adherence_pct=None),
            Assessment(assessment_date=date(2025, 3, 1), values={}, adherence_pct=None),
        ],
    )
    line_missing = build_adherence_line(client_no_adh)
    assert "Adherence not recorded for this block" in line_missing


def test_build_baseline_instruction_directives():
    client = Client(
        client_id="client-001",
        display_name="Alex Smith",
        goal="Body recomposition",
        training_frequency="4 days/week",
        daily_step_goal=8000,
        assessments=[
            Assessment(
                assessment_date=date(2025, 1, 1),
                values={"weight_kg": 75.5, "body_fat_pct": 18.0},
            )
        ],
    )
    instruction = build_baseline_instruction(client)

    assert "Alex Smith" in instruction
    assert "client-001" in instruction
    assert "Body recomposition" in instruction
    assert "4 days/week" in instruction
    assert "8000" in instruction
    assert "75.5 kg" in instruction
    assert "18.0 %" in instruction
    assert "REMOVE AND REPLACE every 'Please fill:' placeholder." in instruction
    assert "You MUST NOT calculate, estimate, round, infer, or invent" in instruction


def test_build_report_section_html_assembly():
    client = Client(
        client_id="client-001",
        display_name="Alex Smith",
        goal="Fat loss",
        assessments=[
            Assessment(assessment_date=date(2025, 1, 1), values={"weight_kg": 80.0}),
            Assessment(assessment_date=date(2025, 3, 1), values={"weight_kg": 75.0}, adherence_pct=90.0),
        ],
    )
    chart_url = "https://api.superdocs.app/images/client-001-trend.png"
    section = build_report_section_html(client, chart_url)

    assert '<h2 data-report-block="1">Progress Report — 2025-03-01</h2>' in section
    assert '<table data-report-section="comparison-table">' in section
    assert "90% of prescribed sessions completed" in section
    assert f'src="{chart_url}"' in section
    assert 'data-report-section="trend-chart"' in section


def test_build_narrative_instruction_content():
    client = Client(
        client_id="client-001",
        display_name="Alex Smith",
        goal="General strength",
        assessments=[
            Assessment(assessment_date=date(2025, 1, 1), values={}),
            Assessment(assessment_date=date(2025, 3, 1), values={}),
        ],
        program_changes_by_assessment={
            1: [
                ProgramChange(
                    change="Added 1 working set to back squat",
                    reason="Consistently hit top rep target",
                )
            ]
        },
        next_block_goals={
            1: ["Increase deadlift by 5kg", "Maintain 90%+ adherence"]
        },
    )
    narrative_prompt = build_narrative_instruction(client)

    assert "Added 1 working set to back squat (reason: Consistently hit top rep target)" in narrative_prompt
    assert "Increase deadlift by 5kg; Maintain 90%+ adherence" in narrative_prompt
    assert "Keep both sections under 80 words combined." in narrative_prompt
    assert "Do not calculate or modify any number from the comparison table." in narrative_prompt