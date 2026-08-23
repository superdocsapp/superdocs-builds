from app.workflow.calibration_tracker import CalibrationTracker


def test_records_and_reports_a_single_outcome():
    tracker = CalibrationTracker()
    tracker.record_outcome("contract_value", 0.65, approved=True)
    rows = tracker.bucket_report()
    assert len(rows) == 1
    assert rows[0]["field_name"] == "contract_value"
    assert rows[0]["confidence_bucket"] == "0.6-0.8"
    assert rows[0]["approved"] == 1
    assert rows[0]["approval_rate"] == 1.0


def test_bucketing_edges_are_inclusive_of_lower_bound():
    tracker = CalibrationTracker()
    tracker.record_outcome("f", 0.6, approved=True)  # exactly on the edge -> upper bucket
    tracker.record_outcome("f", 0.59999, approved=True)  # just below -> lower bucket
    rows = tracker.bucket_report("f")
    buckets = {r["confidence_bucket"] for r in rows}
    assert "0.6-0.8" in buckets
    assert "0.4-0.6" in buckets


def test_confidence_of_exactly_one_falls_in_the_top_bucket():
    tracker = CalibrationTracker()
    tracker.record_outcome("f", 1.0, approved=True)
    rows = tracker.bucket_report("f")
    assert rows[0]["confidence_bucket"] == "0.8-1.0"


def test_approval_rate_averages_across_multiple_outcomes_in_the_same_bucket():
    tracker = CalibrationTracker()
    tracker.record_outcome("f", 0.75, approved=True)
    tracker.record_outcome("f", 0.72, approved=True)
    tracker.record_outcome("f", 0.78, approved=False)
    rows = tracker.bucket_report("f")
    assert rows[0]["total"] == 3
    assert abs(rows[0]["approval_rate"] - (2 / 3)) < 1e-9


def test_well_calibrated_bucket_has_a_gap_near_zero():
    tracker = CalibrationTracker()
    # bucket 0.6-0.8, midpoint 0.7 -- approve ~70% of the time
    for _ in range(7):
        tracker.record_outcome("f", 0.7, approved=True)
    for _ in range(3):
        tracker.record_outcome("f", 0.7, approved=False)
    rows = tracker.bucket_report("f")
    assert abs(rows[0]["calibration_gap"]) < 0.05


def test_overconfident_bucket_has_a_large_negative_gap():
    tracker = CalibrationTracker()
    # bucket 0.8-1.0 (midpoint ~0.9) but only 20% actually approved
    for _ in range(2):
        tracker.record_outcome("f", 0.9, approved=True)
    for _ in range(8):
        tracker.record_outcome("f", 0.9, approved=False)
    rows = tracker.bucket_report("f")
    assert rows[0]["calibration_gap"] < -0.5


def test_different_fields_tracked_independently():
    tracker = CalibrationTracker()
    tracker.record_outcome("contract_value", 0.7, approved=True)
    tracker.record_outcome("counterparty_name", 0.7, approved=False)
    cv_rows = tracker.bucket_report("contract_value")
    cp_rows = tracker.bucket_report("counterparty_name")
    assert cv_rows[0]["approval_rate"] == 1.0
    assert cp_rows[0]["approval_rate"] == 0.0


def test_worst_calibrated_fields_excludes_low_sample_buckets():
    tracker = CalibrationTracker()
    # Only 2 samples -- below default min_samples=5, should be excluded
    tracker.record_outcome("sparse_field", 0.9, approved=False)
    tracker.record_outcome("sparse_field", 0.9, approved=False)
    assert tracker.worst_calibrated_fields() == []


def test_worst_calibrated_fields_ranks_by_absolute_gap_descending():
    tracker = CalibrationTracker()
    # well-calibrated field: gap near 0
    for _ in range(6):
        tracker.record_outcome("good_field", 0.7, approved=True)
    for _ in range(4):
        tracker.record_outcome("good_field", 0.7, approved=False)
    # badly miscalibrated field: high confidence, low approval
    for _ in range(1):
        tracker.record_outcome("bad_field", 0.95, approved=True)
    for _ in range(9):
        tracker.record_outcome("bad_field", 0.95, approved=False)

    worst = tracker.worst_calibrated_fields(min_samples=5)
    assert worst[0]["field_name"] == "bad_field"


def test_empty_tracker_reports_nothing():
    tracker = CalibrationTracker()
    assert tracker.bucket_report() == []
    assert tracker.worst_calibrated_fields() == []


# --- suggest_thresholds --------------------------------------------------


def test_suggests_the_lowest_bucket_meeting_the_target_approval_rate():
    tracker = CalibrationTracker()
    # 0.8-1.0 bucket: 95% approval -- meets 90% target
    for _ in range(19):
        tracker.record_outcome("f", 0.9, approved=True)
    tracker.record_outcome("f", 0.9, approved=False)
    # 0.6-0.8 bucket: only 50% approval -- misses target
    for _ in range(5):
        tracker.record_outcome("f", 0.7, approved=True)
    for _ in range(5):
        tracker.record_outcome("f", 0.7, approved=False)

    suggestions = tracker.suggest_thresholds(target_approval_rate=0.9, min_samples=10)
    assert suggestions["f"]["suggested_threshold"] == 0.8


def test_suggests_none_when_even_top_bucket_misses_target():
    tracker = CalibrationTracker()
    for _ in range(5):
        tracker.record_outcome("f", 0.9, approved=True)
    for _ in range(5):
        tracker.record_outcome("f", 0.9, approved=False)  # only 50% at the top bucket

    suggestions = tracker.suggest_thresholds(target_approval_rate=0.9, min_samples=10)
    assert suggestions["f"]["suggested_threshold"] is None
    assert "unreliable" in suggestions["f"]["note"]


def test_fields_below_min_samples_are_omitted_from_suggestions():
    tracker = CalibrationTracker()
    tracker.record_outcome("sparse_field", 0.9, approved=True)
    suggestions = tracker.suggest_thresholds(min_samples=10)
    assert "sparse_field" not in suggestions


def test_suggest_thresholds_never_applies_anything_only_reports():
    """Sanity check on the contract: calling suggest_thresholds must not
    mutate the tracker's own recorded stats."""
    tracker = CalibrationTracker()
    for _ in range(10):
        tracker.record_outcome("f", 0.9, approved=True)
    before = tracker.bucket_report("f")
    tracker.suggest_thresholds()
    after = tracker.bucket_report("f")
    assert before == after


def test_walk_stops_at_first_bucket_from_top_that_misses_even_if_lower_bucket_would_pass():
    """A lower bucket having a spuriously high approval rate (small
    sample noise) should not override a real miss immediately above
    it -- the function should stop walking down as soon as it hits a
    miss, not cherry-pick the best remaining bucket."""
    tracker = CalibrationTracker()
    for _ in range(10):
        tracker.record_outcome("f", 0.9, approved=True)  # top bucket: 100%
    for _ in range(10):
        tracker.record_outcome("f", 0.7, approved=False)  # next bucket down: 0% -- should stop here
    for _ in range(10):
        tracker.record_outcome("f", 0.5, approved=True)  # lower bucket: 100% again, should be ignored

    suggestions = tracker.suggest_thresholds(target_approval_rate=0.9, min_samples=10)
    assert suggestions["f"]["suggested_threshold"] == 0.8  # stopped at the top bucket, didn't skip down to 0.4
