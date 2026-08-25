"""
@file: backend/tests/test_token_budget.py
@description: Tests the request-sizing layer against the two ways a token ceiling can be
    violated, which are opposite mistakes that produce errors naming neither cause: ask
    for too much and Groq rejects the request with 413 before generating anything, ask
    for too little and a reasoning model returns an empty completion that Groq reports as
    400 json_validate_failed with failed_generation: "". Both must be recognised as
    budget failures and answered by sending less at once, not by retrying identically.
@flow: drive the real GroqClient over an httpx MockTransport -> assert the ceiling is
    learned from x-ratelimit headers rather than assumed -> assert an over-budget request
    is refused before any HTTP call -> assert a 413 and an empty generation both split
    the batch and complete.
@dependencies: httpx.MockTransport, backend.services.groq_client, token_budget, batching
"""

from __future__ import annotations

import json

import httpx
import pytest

from backend.config import settings
from backend.services import token_budget
from backend.services.batching import indexed_json_call
from backend.services.groq_client import (
    GroqClient,
    GroqRequestTooLarge,
    GroqTruncatedOutput,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _forget_learned_limits():
    """Each test starts with no observed limits, as a fresh process would."""
    token_budget.reset_observed_limits()
    yield
    token_budget.reset_observed_limits()


def _ok_body(content: str, *, prompt_tokens: int = 200, completion: int = 50) -> dict:
    return {
        "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion},
    }


_LIMIT_HEADERS = {
    "x-ratelimit-limit-tokens": "8000",
    "x-ratelimit-remaining-tokens": "7900",
    "x-ratelimit-reset-tokens": "705ms",
}


def _client(handler) -> GroqClient:
    transport = httpx.MockTransport(handler)
    return GroqClient(
        api_key="test-key", client=httpx.AsyncClient(transport=transport)
    )


# ---------------------------------------------------------------- header parsing


def test_duration_parsing_covers_the_formats_groq_actually_sends():
    assert token_budget.parse_duration("705ms") == pytest.approx(0.705)
    assert token_budget.parse_duration("1.5s") == pytest.approx(1.5)
    assert token_budget.parse_duration("27m21.6s") == pytest.approx(27 * 60 + 21.6)
    assert token_budget.parse_duration("2m") == pytest.approx(120)
    assert token_budget.parse_duration("") is None
    assert token_budget.parse_duration("soon") is None


def test_ceiling_comes_from_the_response_header_not_a_constant():
    """The limit is whatever the provider says it is, including a larger tier."""
    token_budget.observe_headers({"x-ratelimit-limit-tokens": "30000"})
    assert token_budget.token_ceiling() == 30000

    token_budget.observe_headers({"x-ratelimit-limit-tokens": "6000"})
    assert token_budget.token_ceiling() == 6000


def test_ceiling_is_learned_from_the_413_body_as_well():
    """A rejected request states the ceiling it was measured against."""
    token_budget.note_limit_from_error(
        "Request too large for model `openai/gpt-oss-120b` ... on tokens per minute "
        "(TPM): Limit 12000, Requested 15004, please reduce your message size"
    )
    assert token_budget.token_ceiling() == 12000


async def test_limits_are_recorded_from_a_successful_call(monkeypatch):
    monkeypatch.setattr(settings, "groq_model", "openai/gpt-oss-120b")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_ok_body("hello"), headers=_LIMIT_HEADERS)

    client = _client(handler)
    try:
        await client.complete("sys", "user", max_tokens=256)
    finally:
        await client.aclose()

    limits = token_budget.current_limits()
    assert limits.limit_tokens == 8000
    assert limits.remaining_tokens == 7900
    assert limits.reset_tokens_s == pytest.approx(0.705)


# ---------------------------------------------------------------- sizing


async def test_request_max_tokens_is_sized_to_fit_under_the_ceiling(monkeypatch):
    """prompt + max_tokens must land under the ceiling, because Groq counts it up front.

    The reported 413 was 690 prompt tokens plus a 9,216-token completion request against
    an 8,000-token ceiling: rejected before a single token was generated.
    """
    monkeypatch.setattr(settings, "groq_model", "openai/gpt-oss-120b")
    monkeypatch.setattr(settings, "groq_tpm_limit", 8000)
    monkeypatch.setattr(settings, "groq_tpm_headroom", 600)

    sent: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(200, json=_ok_body('{"ok": true}'), headers=_LIMIT_HEADERS)

    client = _client(handler)
    try:
        # Ask for far more than the ceiling allows.
        await client.complete_json(
            "system prompt", "user prompt",
            untrusted_content="x" * 2000,
            max_tokens=9216,
            min_completion_tokens=512,
        )
    finally:
        await client.aclose()

    body = sent[0]
    prompt_chars = sum(len(m["content"]) for m in body["messages"])
    estimate = token_budget.estimate_tokens(*(m["content"] for m in body["messages"]))
    assert estimate + body["max_tokens"] <= 8000 - 600, (
        f"request totals {estimate + body['max_tokens']} tokens, over the ceiling"
    )
    assert body["max_tokens"] < 9216, "max_tokens was not reduced to fit"
    assert body["reasoning_effort"] == "low", "reasoning cap must stay for gpt-oss"
    assert prompt_chars > 0


async def test_an_unfittable_request_is_refused_without_calling_the_api(monkeypatch):
    """A request that cannot fit must cost nothing — no HTTP, no rate-limit spend."""
    monkeypatch.setattr(settings, "groq_model", "openai/gpt-oss-120b")
    monkeypatch.setattr(settings, "groq_tpm_limit", 8000)

    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=_ok_body("{}"), headers=_LIMIT_HEADERS)

    client = _client(handler)
    try:
        with pytest.raises(GroqRequestTooLarge) as excinfo:
            await client.complete_json(
                "system", "user",
                untrusted_content="y" * 20000,   # ~6k tokens of prompt
                max_tokens=3072,
                min_completion_tokens=3072,      # cannot both fit under 8000
            )
    finally:
        await client.aclose()

    assert calls == 0, "an impossible request was still sent"
    assert "over the" in str(excinfo.value)


async def test_reasoning_models_keep_a_reserve_on_top_of_the_callers_floor(monkeypatch):
    """gpt-oss draws reasoning from the answer's budget, so the answer needs extra room.

    This is the constraint that made the original multiplier look necessary: at a budget
    sized only for the answer, the reasoning consumed it and the completion came back
    empty. The fix is a stated reserve, not a blind ×3.
    """
    monkeypatch.setattr(settings, "groq_model", "openai/gpt-oss-120b")
    monkeypatch.setattr(settings, "groq_reasoning_reserve_tokens", 512)

    sent: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(200, json=_ok_body('{"ok":1}'), headers=_LIMIT_HEADERS)

    client = _client(handler)
    try:
        await client.complete_json(
            "sys", "user", max_tokens=600, min_completion_tokens=600
        )
    finally:
        await client.aclose()

    assert sent[0]["max_tokens"] >= 600 + 512, (
        "no room was reserved for reasoning tokens"
    )


# ---------------------------------------------------------------- failure typing


async def test_empty_completion_is_reported_as_a_budget_failure(monkeypatch):
    """An empty answer must not travel on as a valid completion."""
    monkeypatch.setattr(settings, "groq_model", "openai/gpt-oss-120b")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": ""}, "finish_reason": "length"}],
                "usage": {"prompt_tokens": 690, "completion_tokens": 3072},
            },
            headers=_LIMIT_HEADERS,
        )

    client = _client(handler)
    try:
        with pytest.raises(GroqTruncatedOutput):
            await client.complete_json("sys", "user", max_tokens=3072)
    finally:
        await client.aclose()


async def test_json_validate_failed_on_an_empty_generation_is_typed_as_truncation(
    monkeypatch,
):
    """The 400 that names output which never existed is a budget failure, not a prompt one."""
    monkeypatch.setattr(settings, "groq_model", "openai/gpt-oss-120b")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "error": {
                    "message": "Failed to validate JSON. Please adjust your prompt.",
                    "code": "json_validate_failed",
                    "failed_generation": "",
                }
            },
            headers=_LIMIT_HEADERS,
        )

    client = _client(handler)
    try:
        with pytest.raises(GroqTruncatedOutput):
            await client.complete_json("sys", "user", max_tokens=2048)
    finally:
        await client.aclose()


async def test_413_is_typed_as_too_large_and_not_retried_identically(monkeypatch):
    monkeypatch.setattr(settings, "groq_model", "openai/gpt-oss-120b")
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            413,
            json={
                "error": {
                    "message": (
                        "Request too large for model `openai/gpt-oss-120b` ... on tokens "
                        "per minute (TPM): Limit 8000, Requested 9904, please reduce "
                        "your message size and try again."
                    ),
                    "code": "rate_limit_exceeded",
                }
            },
            headers=_LIMIT_HEADERS,
        )

    client = _client(handler)
    try:
        with pytest.raises(GroqRequestTooLarge):
            await client.complete_json("sys", "user", max_tokens=1024)
    finally:
        await client.aclose()

    assert calls == 1, f"a 413 was retried unchanged {calls} times"


# ---------------------------------------------------------------- splitting


async def test_a_413_splits_the_batch_and_completes(monkeypatch):
    """A batch that does not fit is halved and retried, not failed."""
    monkeypatch.setattr(settings, "groq_model", "openai/gpt-oss-120b")
    sizes: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        user = body["messages"][1]["content"]
        markers = [int(t.split("]")[0]) for t in user.split("[")[1:] if "]" in t]
        markers = [m for m in markers if 0 <= m < 8]
        sizes.append(len(markers))
        if len(markers) > 2:
            return httpx.Response(
                413,
                json={"error": {"message": "Request too large ... Limit 8000, "
                                           "Requested 9904"}},
                headers=_LIMIT_HEADERS,
            )
        payload = {"results": [{"index": m, "issue": f"issue {m}"} for m in markers]}
        return httpx.Response(
            200, json=_ok_body(json.dumps(payload)), headers=_LIMIT_HEADERS
        )

    client = _client(handler)
    try:
        outcome = await indexed_json_call(
            client,
            system="You extract structured facts. Return json.",
            instruction=lambda n: f"Extract facts from these {n} records.",
            records=[f"record {i} text" for i in range(8)],
            per_record_output_tokens=72,
            max_output_tokens=3072,
        )
    finally:
        await client.aclose()

    assert outcome.splits >= 2, "the batch was not split"
    assert sorted(outcome.results) == list(range(8)), (
        f"records were lost or renumbered by the split: {sorted(outcome.results)}"
    )
    for index, item in outcome.results.items():
        assert item["issue"] == f"issue {index}", (
            "a split reattached one record's result to another record"
        )
    assert max(sizes) == 8 and min(sizes) <= 2


async def test_an_empty_generation_also_splits_the_batch(monkeypatch):
    """The 400 that means "the answer did not fit" must halve the batch too."""
    monkeypatch.setattr(settings, "groq_model", "openai/gpt-oss-120b")

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        user = body["messages"][1]["content"]
        markers = [
            int(t.split("]")[0])
            for t in user.split("[")[1:]
            if "]" in t and t.split("]")[0].isdigit()
        ]
        markers = [m for m in markers if 0 <= m < 4]
        if len(markers) > 1:
            return httpx.Response(
                400,
                json={
                    "error": {
                        "message": "Failed to validate JSON.",
                        "code": "json_validate_failed",
                        "failed_generation": "",
                    }
                },
                headers=_LIMIT_HEADERS,
            )
        payload = {"results": [{"index": m, "issue": "x"} for m in markers]}
        return httpx.Response(
            200, json=_ok_body(json.dumps(payload)), headers=_LIMIT_HEADERS
        )

    client = _client(handler)
    try:
        outcome = await indexed_json_call(
            client,
            system="You extract structured facts. Return json.",
            instruction=lambda n: f"Extract facts from these {n} records.",
            records=[f"record {i}" for i in range(4)],
            per_record_output_tokens=72,
            max_output_tokens=3072,
        )
    finally:
        await client.aclose()

    assert sorted(outcome.results) == [0, 1, 2, 3]
    assert outcome.calls >= 4, "the batch was not split down to single records"


async def test_a_single_record_that_cannot_fit_fails_rather_than_looping(monkeypatch):
    """Splitting has a floor. One record that still will not fit is a real failure."""
    monkeypatch.setattr(settings, "groq_model", "openai/gpt-oss-120b")
    monkeypatch.setattr(settings, "groq_tpm_limit", 8000)
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            413,
            json={"error": {"message": "Request too large ... Limit 8000, "
                                       "Requested 20000"}},
            headers=_LIMIT_HEADERS,
        )

    client = _client(handler)
    try:
        with pytest.raises(GroqRequestTooLarge):
            await indexed_json_call(
                client,
                system="You extract structured facts. Return json.",
                instruction=lambda n: f"Extract facts from these {n} records.",
                records=["one enormous record"],
                per_record_output_tokens=72,
                max_output_tokens=3072,
            )
    finally:
        await client.aclose()

    assert calls <= 2, f"splitting looped: {calls} calls for one record"


async def test_the_prompt_estimator_self_corrects_from_real_usage():
    """A response's real prompt_tokens tightens the estimate for the next request."""
    before = token_budget.estimate_tokens("x" * 3200)
    # A response reporting far more prompt tokens than we assumed for that many chars.
    token_budget.calibrate(prompt_chars=3200, actual_prompt_tokens=1600)
    after = token_budget.estimate_tokens("x" * 3200)
    assert after > before, "the estimator ignored evidence that it was under-counting"


async def test_untrusted_source_text_is_trimmed_to_what_fits_and_says_so(monkeypatch):
    """A long prior digest must be trimmed by token budget, not by a guessed char cap.

    The old code sliced 20,000 characters — roughly 6,000 tokens — which on an
    8,000-token ceiling left no room for the answer, so the request was rejected outright
    rather than answered from a shorter excerpt.
    """
    monkeypatch.setattr(settings, "groq_model", "openai/gpt-oss-120b")
    monkeypatch.setattr(settings, "groq_tpm_limit", 8000)
    monkeypatch.setattr(settings, "groq_tpm_headroom", 600)

    long_text = "theme paragraph. " * 4000  # ~68k characters
    excerpt, note = token_budget.fit_untrusted_excerpt(
        long_text, fixed_prompt="system prompt " * 50, answer_tokens=2048
    )

    assert len(excerpt) < len(long_text), "nothing was trimmed"
    assert note and "does not fit" in note, "the truncation was silent"
    # The excerpt plus its answer must actually fit.
    total = token_budget.estimate_tokens(excerpt) + 2048 + 512
    assert total <= 8000 - 600, f"trimmed excerpt still does not fit: {total} tokens"

    # A short source is passed through untouched and reported as untouched.
    short, note2 = token_budget.fit_untrusted_excerpt(
        "one short digest", fixed_prompt="sys", answer_tokens=512
    )
    assert short == "one short digest"
    assert note2 == ""


async def test_a_ceiling_error_degrades_theme_naming_rather_than_failing_the_run(
    monkeypatch,
):
    """Theme names are a label; the clustering is the analysis.

    A request too large to fit must cost the labels and disclose it, not discard findings
    that are already complete. classify and extract deliberately do NOT behave this way —
    for them the answer to an oversized request is to split it.
    """
    from backend.services.groq_client import LLMUsage
    from backend.services.llm_gate import run_with_fallback

    async def _too_large():
        raise GroqRequestTooLarge("prompt plus answer is over the ceiling")

    gated = await run_with_fallback(
        "theme", _too_large, lambda: {"themes": []}, degrade_on_budget_error=True
    )
    assert gated.degraded is True
    assert "ceiling" in gated.reason

    # Without the opt-in the error propagates, so the caller splits instead.
    with pytest.raises(GroqRequestTooLarge):
        await run_with_fallback("extract", _too_large, lambda: {"results": []})
