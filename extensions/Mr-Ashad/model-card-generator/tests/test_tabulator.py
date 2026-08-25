"""Tests for BenchmarkTabulator, Metric Formatting, Deltas, and Sample Mode."""

import pytest
from pathlib import Path
from src.tabulator import BenchmarkTabulator


def test_tabulator_loads_json_and_calculates_deltas(sample_eval_json_path):
    """Verify loading evaluation JSON and calculating positive, negative, and zero deltas."""
    tabulator = BenchmarkTabulator()
    data = tabulator.load_eval_data(sample_eval_json_path)

    assert "results" in data
    assert len(data["results"]) == 9

    records = tabulator.process_records(data["results"], sample_mode=False)
    assert len(records) == 9

    # Check MMLU record (score=88.4, baseline=84.1 -> delta = +4.3%)
    mmlu_rec = next(r for r in records if r["task_id"] == "mmlu")
    assert mmlu_rec["score"] == 88.4
    assert mmlu_rec["baseline_score"] == 84.1
    assert mmlu_rec["delta_val"] == 4.3
    assert "▲ +4.3%" in mmlu_rec["delta_str"]
    assert mmlu_rec["domain"] == "General Knowledge & Reasoning"


def test_tabulator_loads_csv_correctly(sample_eval_csv_path):
    """Verify loading CSV evaluation artifact and formatting properly."""
    tabulator = BenchmarkTabulator()
    data = tabulator.load_eval_data(sample_eval_csv_path)

    assert len(data["results"]) == 9
    gsm8k_rec = tabulator.enrich_record(next(r for r in data["results"] if r["task_id"] == "gsm8k"))
    
    assert gsm8k_rec["score"] == 93.6
    assert gsm8k_rec["baseline_score"] == 89.2
    assert "▲ +4.4%" in gsm8k_rec["delta_str"]


def test_sample_mode_slices_to_exactly_three_rows(sample_eval_json_path):
    """Verify that sample_mode=True limits output records to exactly 3 rows."""
    tabulator = BenchmarkTabulator()
    data = tabulator.load_eval_data(sample_eval_json_path)

    sliced = tabulator.process_records(data["results"], sample_mode=True)
    assert len(sliced) == 3

    rendered = tabulator.render_markdown_tables(data["results"], sample_mode=True)
    assert "Sample Mode Active" in rendered
    # Count table data rows in the summary table
    summary_rows = [line for line in rendered.splitlines() if line.startswith("| **")]
    # Master table has 3 rows plus domain breakdowns
    assert len(sliced) == 3


def test_negative_and_zero_deltas():
    """Verify correct indicators for regressions (▼) and identical scores (—)."""
    tabulator = BenchmarkTabulator()
    
    # Regression
    reg_rec = tabulator.enrich_record({"task_id": "mmlu", "score": 80.0, "baseline_score": 85.0})
    assert reg_rec["delta_val"] == -5.0
    assert "▼ -5.0%" in reg_rec["delta_str"]

    # Identical
    zero_rec = tabulator.enrich_record({"task_id": "mmlu", "score": 85.0, "baseline_score": 85.0})
    assert zero_rec["delta_val"] == 0.0
    assert "— 0.0%" in zero_rec["delta_str"]

    # No baseline
    no_base = tabulator.enrich_record({"task_id": "mmlu", "score": 85.0})
    assert no_base["baseline_score"] is None
    assert no_base["delta_str"] == "—"


def test_unrecognized_custom_benchmark_graceful_fallback():
    """Verify that unknown benchmarks not in mappings dictionary get clean fallback domains."""
    tabulator = BenchmarkTabulator()
    custom_record = tabulator.enrich_record({
        "task_id": "custom_enterprise_finbench",
        "score": 91.2,
        "metric": "Accuracy",
        "unit": "%"
    })

    assert custom_record["name"] == "CUSTOM ENTERPRISE FINBENCH"
    assert custom_record["domain"] == "Other Benchmarks"
    assert custom_record["score_str"] == "91.2%"
