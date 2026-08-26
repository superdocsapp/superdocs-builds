"""
Proves the resilience fix: run_one_cycle must never raise, even if
something inside it throws unexpectedly -- it should degrade to a
CycleResult with fatal_error set instead of crashing run_cell/run_benchmark
and losing every result collected before it.
"""
from unittest.mock import patch

from bench.runner import run_one_cycle


def test_run_one_cycle_never_raises_even_on_unexpected_exception():
    with patch("bench.runner.SuperDocsClient") as MockClient:
        MockClient.side_effect = RuntimeError("simulated unexpected failure")
        result = run_one_cycle("fake-key", "small", 1)

    assert result.fatal_error is not None
    assert "RuntimeError" in result.fatal_error
    assert result.phases == []
