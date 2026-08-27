from benchmark.metrics import estimate_tokens, cost_usd


def test_estimate_tokens_empty():
    assert estimate_tokens("") == 0


def test_estimate_tokens_scales_with_length():
    short = estimate_tokens("hello world")
    long = estimate_tokens("hello world " * 100)
    assert long > short
    # roughly proportional (within a generous tolerance for the heuristic)
    assert long > short * 50


def test_cost_usd_zero_for_zero_tokens():
    assert cost_usd(0, 0) == 0.0


def test_cost_usd_increases_with_tokens():
    low = cost_usd(100, 100)
    high = cost_usd(10_000, 10_000)
    assert high > low


def test_output_tokens_cost_more_per_token_than_input():
    # documented pricing assumption: output is priced higher than input
    input_only = cost_usd(1000, 0)
    output_only = cost_usd(0, 1000)
    assert output_only > input_only
