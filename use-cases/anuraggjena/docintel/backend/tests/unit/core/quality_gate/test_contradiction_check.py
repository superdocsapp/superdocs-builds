import pytest
from unittest.mock import AsyncMock, MagicMock

from backend.core.quality_gate.contradiction_check import ContradictionCheck, ContradictionResult
from backend.core.quality_gate.checks import CheckStatus


def make_llm(response: ContradictionResult):
    llm = MagicMock()
    llm.generate_structured = AsyncMock(return_value=response)
    return llm


@pytest.mark.asyncio
async def test_skip_with_single_claim():
    check = ContradictionCheck(make_llm(None))
    result = await check.run({"claims": [{"content": "HS code is 1234.56"}]}, {})
    assert result.status == CheckStatus.SKIPPED


@pytest.mark.asyncio
async def test_skip_with_no_claims():
    check = ContradictionCheck(make_llm(None))
    result = await check.run({}, {})
    assert result.status == CheckStatus.SKIPPED


@pytest.mark.asyncio
async def test_pass_no_contradictions():
    response = ContradictionResult(has_contradictions=False, contradictions=[], confidence=0.95)
    llm = make_llm(response)
    check = ContradictionCheck(llm)
    state = {
        "claims": [
            {"content": "Widget A has HS code 8471.30"},
            {"content": "Widget B has HS code 8471.40"},
        ]
    }
    result = await check.run(state, {})
    assert result.status == CheckStatus.PASSED
    assert result.details["claims_checked"] == 2


@pytest.mark.asyncio
async def test_fail_with_contradictions():
    response = ContradictionResult(
        has_contradictions=True,
        contradictions=[
            {
                "claim_a": "HS code is 8471.30",
                "claim_b": "HS code is 9999.99",
                "reason": "Same product, different codes",
            }
        ],
        confidence=0.9,
    )
    llm = make_llm(response)
    check = ContradictionCheck(llm)
    state = {
        "claims": [
            {"content": "HS code is 8471.30"},
            {"content": "HS code is 9999.99"},
        ]
    }
    result = await check.run(state, {})
    assert result.status == CheckStatus.FAILED
    assert result.blocking is True
    assert len(result.details["contradictions"]) == 1


@pytest.mark.asyncio
async def test_warning_on_llm_error():
    llm = MagicMock()
    llm.generate_structured = AsyncMock(side_effect=Exception("LLM unavailable"))
    check = ContradictionCheck(llm)
    state = {
        "claims": [
            {"content": "claim one"},
            {"content": "claim two"},
        ]
    }
    result = await check.run(state, {})
    assert result.status == CheckStatus.WARNING


@pytest.mark.asyncio
async def test_claims_as_strings():
    """Handles claims that are plain strings, not dicts."""
    response = ContradictionResult(has_contradictions=False, contradictions=[], confidence=0.8)
    llm = make_llm(response)
    check = ContradictionCheck(llm)
    state = {"claims": ["claim text one", "claim text two"]}
    result = await check.run(state, {})
    assert result.status == CheckStatus.PASSED
