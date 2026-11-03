from app.workflow.cost_tracker import MODE_ENSEMBLE, MODE_NONE, MODE_PAIRWISE, CostTracker


def test_records_and_reports_a_single_run():
    tracker = CostTracker()
    tracker.record_run(MODE_NONE, operations=4, latency_ms=100.0)
    report = tracker.report()
    assert report[MODE_NONE]["run_count"] == 1
    assert report[MODE_NONE]["total_operations"] == 4
    assert report[MODE_NONE]["avg_operations_per_run"] == 4.0


def test_averages_across_multiple_runs_in_the_same_mode():
    tracker = CostTracker()
    tracker.record_run(MODE_NONE, operations=4, latency_ms=100.0)
    tracker.record_run(MODE_NONE, operations=6, latency_ms=200.0)
    report = tracker.report()
    assert report[MODE_NONE]["avg_operations_per_run"] == 5.0
    assert report[MODE_NONE]["avg_latency_ms_per_run"] == 150.0


def test_multiplier_is_none_without_a_baseline():
    tracker = CostTracker()
    tracker.record_run(MODE_PAIRWISE, operations=8, latency_ms=200.0)
    report = tracker.report()
    assert report[MODE_PAIRWISE]["operations_multiplier_vs_none"] is None


def test_multiplier_computed_against_none_baseline():
    tracker = CostTracker()
    tracker.record_run(MODE_NONE, operations=4, latency_ms=100.0)
    tracker.record_run(MODE_NONE, operations=4, latency_ms=100.0)
    tracker.record_run(MODE_PAIRWISE, operations=8, latency_ms=200.0)
    report = tracker.report()
    assert report[MODE_PAIRWISE]["operations_multiplier_vs_none"] == 2.0


def test_ensemble_multiplier_independent_of_pairwise():
    tracker = CostTracker()
    tracker.record_run(MODE_NONE, operations=4, latency_ms=100.0)
    tracker.record_run(MODE_ENSEMBLE, operations=20, latency_ms=500.0)
    report = tracker.report()
    assert report[MODE_ENSEMBLE]["operations_multiplier_vs_none"] == 5.0


def test_empty_tracker_reports_nothing():
    tracker = CostTracker()
    assert tracker.report() == {}


def test_none_mode_baseline_itself_has_no_self_multiplier_field_confusion():
    tracker = CostTracker()
    tracker.record_run(MODE_NONE, operations=4, latency_ms=100.0)
    report = tracker.report()
    assert report[MODE_NONE]["operations_multiplier_vs_none"] is None
