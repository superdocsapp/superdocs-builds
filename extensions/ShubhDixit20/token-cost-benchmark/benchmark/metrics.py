"""
Token estimation and cost model.

Ground truth: whenever the real SuperDocs API returns usage.input_tokens /
usage.output_tokens, that is used directly (see client.SuperDocsClient.edit).

estimate_tokens() below is ONLY a fallback for offline/mock mode and for
pre-flight budget estimates before a run. It uses the widely-cited ~4
characters-per-token heuristic for English text. This is a documented
approximation, not a claim of tokenizer accuracy — the write-up says so
explicitly rather than presenting mock numbers as measured cost.
"""
from __future__ import annotations

CHARS_PER_TOKEN = 4.0  # documented heuristic, see module docstring

# Illustrative per-1K-token pricing, kept as a config dict so it's a data
# change, not a code change, if real pricing needs to be plugged in later.
PRICING_USD_PER_1K = {
    "input": 0.003,
    "output": 0.015,
}


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, round(len(text) / CHARS_PER_TOKEN))


def cost_usd(input_tokens: int, output_tokens: int) -> float:
    return (
        (input_tokens / 1000) * PRICING_USD_PER_1K["input"]
        + (output_tokens / 1000) * PRICING_USD_PER_1K["output"]
    )
