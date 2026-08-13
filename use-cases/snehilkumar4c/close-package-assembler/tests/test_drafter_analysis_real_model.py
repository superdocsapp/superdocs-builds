"""A real-model check on Task 2's analysis quality, not just plumbing. The
fake-client tests (test_drafter_analysis.py, test_llm_client.py) prove our
code handles whatever the model returns correctly -- they cannot prove the
model actually identifies real, correctly-cited performance obligations,
price allocations, and timing conclusions from a real contract. Same VCR
pattern as Task 1's test_extract_real_model.py: record once against a real
model, replay after.

Uses the hardware+warranty fixture specifically because it's the one
fixture where a genuine judgement call (is the extended warranty a
distinct performance obligation?) is stated directly in the contract's own
text -- the strongest real-model test of whether the model actually
produces is_judgement=True for something that requires judgement, not just
extracts plain facts.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from core.citations import quote_is_verifiable
from core.llm import LLMClient

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "drafter"
CASSETTE_DIR = Path(__file__).parent / "fixtures" / "cassettes"

_cassette_exists = (
    CASSETTE_DIR / "test_real_model_analyzes_hardware_warranty_contract.yaml"
).exists()
_recording_requested = os.environ.get("RECORD_LLM_CASSETTES") == "1"

pytestmark = pytest.mark.skipif(
    not (_cassette_exists or _recording_requested),
    reason=(
        "No recorded cassette, and RECORD_LLM_CASSETTES=1 was not set. Run "
        "with a real ANTHROPIC_API_KEY and that flag to record once."
    ),
)


@pytest.mark.vcr()
def test_real_model_analyzes_hardware_warranty_contract() -> None:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "sk-ant-placeholder-for-replay")
    llm = LLMClient(api_key=api_key)

    contract_text = (FIXTURES_DIR / "contract_hardware_warranty.txt").read_text()
    result = llm.analyze_revenue_recognition(contract_text)

    obligations = result["performance_obligations"]
    allocations = result["price_allocations"]
    timings = result["timing_conclusions"]

    assert len(obligations) >= 2, f"expected at least 2 obligations (equipment + warranty), got {obligations}"
    assert len(allocations) >= 2, f"expected at least 2 price allocations, got {allocations}"
    assert len(timings) >= 2, f"expected at least 2 timing conclusions, got {timings}"

    # Every citation across all three arrays must be genuinely verifiable
    # against the real contract text -- the real-model version of the same
    # guarantee drafter/analysis.py enforces in code.
    all_items = obligations + allocations + timings
    unverifiable = [
        item
        for item in all_items
        if not quote_is_verifiable(item.get("source_quote", ""), contract_text)
    ]
    assert not unverifiable, f"model produced unverifiable citations: {unverifiable}"

    # The model should find the headline dollar figures a human would
    # expect -- not just produce some verifiable-but-useless items.
    allocation_amounts = " ".join(a["allocated_amount"] for a in allocations)
    assert "540,000" in allocation_amounts or "540000" in allocation_amounts, (
        f"model missed the equipment price entirely: {allocations}"
    )
    assert "81,000" in allocation_amounts or "81000" in allocation_amounts, (
        f"model missed the extended warranty price entirely: {allocations}"
    )

    # THE core proof for this fixture: the contract's own text explains why
    # the extended warranty is a distinct performance obligation -- a real
    # judgement call. The model should recognize this as requiring
    # judgement, not just state it as a plain, unexamined fact.
    warranty_obligations = [
        o for o in obligations if "warranty" in o["description"].lower() or "warranty" in o["obligation_id"].lower()
    ]
    assert warranty_obligations, f"model did not identify the extended warranty as an obligation at all: {obligations}"
    assert any(o["is_judgement"] for o in warranty_obligations), (
        "model did not flag the warranty-distinctness determination as a "
        f"judgement call: {warranty_obligations}"
    )

    # And the recognition timing should differ between the two obligations
    # (equipment recognized at a point in time on acceptance; warranty
    # recognized over the 36-month coverage period) -- proof the model
    # isn't just stamping the same pattern on everything.
    patterns = {t["recognition_pattern"] for t in timings}
    assert patterns == {"point_in_time", "over_time"}, (
        f"expected both recognition patterns to appear (equipment vs. warranty), got {patterns}"
    )
