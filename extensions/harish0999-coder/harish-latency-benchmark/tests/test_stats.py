from bench.client import PhaseResult
from bench.stats import compute_phase_stats, load_generator_overhead_check, _percentile


def _ok(latency, phase="upload"):
    return PhaseResult(phase=phase, latency_s=latency, status_code=200,
                        rate_limited=False, ops_charged=1, body={})


def _rate_limited(phase="upload"):
    return PhaseResult(phase=phase, latency_s=0.01, status_code=429,
                        rate_limited=True, ops_charged=None, body={})


def _errored(phase="upload"):
    return PhaseResult(phase=phase, latency_s=5.0, status_code=500,
                        rate_limited=False, ops_charged=None, body={}, error="server error")


def test_percentile_basic():
    vals = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert _percentile(vals, 50) == 3.0
    assert _percentile(vals, 0) == 1.0
    assert _percentile(vals, 100) == 5.0


def test_percentile_empty():
    import math
    assert math.isnan(_percentile([], 50))


def test_rate_limited_excluded_from_latency_but_counted():
    results = [_ok(1.0), _ok(2.0), _rate_limited(), _rate_limited()]
    stats = compute_phase_stats("upload", results)
    assert stats.n_total == 4
    assert stats.n_rate_limited == 2
    assert stats.n_ok == 2
    assert stats.median_s == 1.5
    assert stats.rate_limit_fraction == 0.5


def test_errors_excluded_from_latency_and_from_rate_limit_count():
    results = [_ok(1.0), _errored()]
    stats = compute_phase_stats("upload", results)
    assert stats.n_ok == 1
    assert stats.n_errored == 1
    assert stats.n_rate_limited == 0
    assert stats.median_s == 1.0


def test_tail_latency_differs_from_median_under_skew():
    results = [_ok(0.1) for _ in range(9)] + [_ok(10.0)]
    stats = compute_phase_stats("upload", results)
    assert stats.median_s < 1.0
    assert stats.p99_s > 5.0
    assert stats.p99_s != stats.median_s


def test_load_generator_overhead_flags_when_dispatch_is_slow():
    slow = [0.2, 0.3, 0.25]
    result = load_generator_overhead_check(slow, concurrency=4, warn_threshold_s=0.05)
    assert result["checked"] is True
    assert result["generator_is_bottleneck"] is True


def test_load_generator_overhead_ok_when_dispatch_is_fast():
    fast = [0.001, 0.002, 0.0015]
    result = load_generator_overhead_check(fast, concurrency=4, warn_threshold_s=0.05)
    assert result["generator_is_bottleneck"] is False
