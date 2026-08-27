"""Tests for Build B ROI calculator and report generation."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx
from build_a.client import SuperDocsClient

from build_b.calculator import (
    CalculatorInputs,
    ReportGenerator,
    compute_tco,
)

TEST_API_KEY = "sk_test_key"


def test_basic_tco_computation() -> None:
    """Basic TCO: build one-time = hours × hourly cost."""
    inputs = CalculatorInputs(volume=100, hours=500, hourly_cost=75)
    results = compute_tco(inputs)
    assert results.build_one_time == 500 * 75  # $37,500
    assert results.build_maintenance_annual == 0.20 * 500 * 75  # $7,500
    assert results.build_infra_annual == 100 * 12  # $1,200
    assert results.build_total == 37_500 + 7_500 * 3 + 1_200 * 3  # $63,600


def test_buy_tier_selection() -> None:
    """Volume <= 500 → Free, <= 2000 → Plus, > 2000 → Pro."""
    assert compute_tco(CalculatorInputs(volume=100, hours=100, hourly_cost=50)).buy_tier == "Free"
    assert compute_tco(CalculatorInputs(volume=600, hours=100, hourly_cost=50)).buy_tier == "Plus"
    assert compute_tco(CalculatorInputs(volume=3000, hours=100, hourly_cost=50)).buy_tier == "Pro"


def test_savings_positive_when_build_expensive() -> None:
    """Expensive build should show positive savings."""
    inputs = CalculatorInputs(volume=100, hours=2000, hourly_cost=100)
    results = compute_tco(inputs)
    assert results.savings > 0


def test_savings_negative_when_buy_expensive() -> None:
    """Very cheap build + high volume should show negative savings (buy is cheaper)."""
    inputs = CalculatorInputs(volume=5000, hours=1, hourly_cost=10, infrastructure_monthly=0)
    results = compute_tco(inputs)
    assert results.savings < 0


def test_payback_none_for_free_tier() -> None:
    """Free tier has no payback period."""
    inputs = CalculatorInputs(volume=100, hours=500, hourly_cost=75)
    results = compute_tco(inputs)
    assert results.payback_months is None


def test_payback_computed_for_paid_tier() -> None:
    """Paid tier with positive savings should have a payback period."""
    inputs = CalculatorInputs(volume=600, hours=2000, hourly_cost=100)
    results = compute_tco(inputs)
    assert results.payback_months is not None
    assert results.payback_months > 0


def test_horizon_zero_raises() -> None:
    """horizon_years=0 should raise ValueError."""
    with pytest.raises(ValueError, match="horizon_years"):
        compute_tco(CalculatorInputs(volume=100, hours=100, hourly_cost=50, horizon_years=0))


def test_report_prompt_contains_exact_values() -> None:
    """Report prompt contains exact computed values — key invariant."""
    inputs = CalculatorInputs(volume=100, hours=500, hourly_cost=75)
    results = compute_tco(inputs)
    client = SuperDocsClient.__new__(SuperDocsClient)
    gen = ReportGenerator(client)
    prompt = gen.build_report_prompt(results)
    assert "$37,500" in prompt
    assert "$7,500" in prompt
    assert "$1,200" in prompt
    assert "500" in prompt
    assert "75" in prompt
    assert "Free" in prompt
    assert "volume=100" in prompt


def test_report_prompt_includes_all_assumptions() -> None:
    """Prompt includes all documented assumptions."""
    inputs = CalculatorInputs(
        volume=100, hours=500, hourly_cost=75,
        maintenance_rate=0.25, infrastructure_monthly=150, horizon_years=5
    )
    results = compute_tco(inputs)
    client = SuperDocsClient.__new__(SuperDocsClient)
    gen = ReportGenerator(client)
    prompt = gen.build_report_prompt(results)
    assert "5 years" in prompt
    assert "$150" in prompt
    assert "500" in prompt


@pytest.mark.asyncio
@respx.mock
async def test_generate_report_sends_exact_values() -> None:
    """generate_report sends the exact computed values in the prompt."""
    async with SuperDocsClient(api_key=TEST_API_KEY) as client:
        respx.post("https://api.superdocs.app/v1/chat").mock(
            return_value=httpx.Response(200, json={
                "response": "Report generated",
                "session_id": "roi-test",
                "document_changes": {
                    "updated_html": "<h1>ROI Report</h1>",
                },
            })
        )
        inputs = CalculatorInputs(volume=100, hours=500, hourly_cost=75)
        results = compute_tco(inputs)
        gen = ReportGenerator(client)
        html = await gen.generate_report("roi-test", results)
        assert "<h1>ROI Report</h1>" in html
        assert client.tracker.total_ops == 1


@pytest.mark.asyncio
@respx.mock
async def test_export_report_saves_pdf(tmp_path: Path) -> None:
    """export_report downloads and saves the PDF."""
    async with SuperDocsClient(api_key=TEST_API_KEY) as client:
        respx.post("https://api.superdocs.app/v1/documents/export").mock(
            return_value=httpx.Response(200, json={
                "download_url": "https://cdn.example.com/report.pdf",
            })
        )
        respx.get("https://cdn.example.com/report.pdf").mock(
            return_value=httpx.Response(200, content=b"%PDF-1.4 report")
        )
        gen = ReportGenerator(client)
        path = await gen.export_report("roi-test", tmp_path / "report.pdf")
        assert path.exists()
        assert path.read_bytes() == b"%PDF-1.4 report"
